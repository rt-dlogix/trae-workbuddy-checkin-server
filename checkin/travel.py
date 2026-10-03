"""WorkBuddy 派猫猫旅行状态机（手机端整合版）

凭证来源：checkin.store 读取 platform=workbuddy 条目（与签到账户共用 config.yaml）。
接口鉴权：Bearer 直连【2026-09-26 实测，无需浏览器/Cookie】。
状态机：idle→traveling→arrived→idle；领完立即再派，吃满每日次数；
有每日上限（服务端规则），次日自动恢复；到点未领不丢，下次运行自动补领。
调度：Termux crontab 触发 python -m checkin --travel。
"""
from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger("checkin")

BASE = "https://www.workbuddy.cn"
PREFIX = "/activity/growth/buddy/travel"
AUTO_DEPART = True  # 领完立即再派，吃满每日次数


def _req(path: str, token: str, uid: str, method: str = "GET", body: dict | None = None):
    """调用旅行接口；返回 (status_code, json_dict)"""
    url = BASE + path
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-User-Id": uid,
        "Referer": "https://www.workbuddy.cn/profile/growth-center",
        "User-Agent": "WorkBuddy/1.0",
    }
    try:
        if method == "POST":
            resp = requests.request(method, url, headers=headers, json=body or {}, timeout=25)
        else:
            resp = requests.request(method, url, headers=headers, timeout=25)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}
    except requests.RequestException as e:
        return -1, {"message": str(e)}


def _travel_one(token: str, uid: str, remark: str) -> tuple[bool, str]:
    """执行单个账户的旅行状态机一轮。返回 (ok, message)"""
    code, st = _req(f"{PREFIX}/status", token, uid)
    if code != 200:
        return False, f"status HTTP {code}，token 失效，请重新提取"
    data = st.get("data") or {}
    state = data.get("state", "unknown")
    if data.get("daily_limit_reached"):
        return True, "已达每日上限，跳过"
    loc = (data.get("location") or {}).get("name", "")

    if state == "arrived":
        code, claim = _req(f"{PREFIX}/claim", token, uid, method="POST")
        if code == 200 and claim.get("code", 0) == 0:
            d = claim.get("data") or {}
            pts = d.get("reward_credit") or d.get("points") or "?"
            # 领完立即再派一单，吃满每日次数
            time.sleep(random.uniform(1, 3))
            if AUTO_DEPART:
                code2, cfg = _req(f"{PREFIX}/config", token, uid)
                loc_id = None
                if code2 == 200:
                    locs = (cfg.get("data") or {}).get("locations") or []
                    if locs:
                        loc_id = random.choice(locs).get("id")
                _req(f"{PREFIX}/depart", token, uid, method="POST",
                     body={"location_id": loc_id})
            return True, f"领取旅行奖励 +{pts}（{loc}），并已再派一单"
        return False, f"claim 失败：{(claim.get('message') or '')[:60]}"

    if state == "idle":
        if not AUTO_DEPART:
            return True, "仅领取模式，跳过派出"
        loc_id = None
        code, cfg = _req(f"{PREFIX}/config", token, uid)
        if code == 200:
            locs = (cfg.get("data") or {}).get("locations") or []
            if locs:
                loc_id = random.choice(locs).get("id")
        code, dep = _req(f"{PREFIX}/depart", token, uid, method="POST",
                         body={"location_id": loc_id})
        if code == 200 and dep.get("code", 0) == 0:
            eta = (dep.get("data") or {}).get("arrive_at", "待定")
            return True, f"派出成功，预计到点 {eta}"
        return False, f"depart 失败：{(dep.get('message') or '')[:60]}"

    if state == "traveling":
        return True, f"旅行中（{loc}），等下次调度领取"

    return False, f"未知 state={state}"


def run_travel(store) -> int:
    """读取 store 中所有 workbuddy 账户，执行旅行状态机。返回 0/1。"""
    accounts = store.accounts()
    wb = [a for a in accounts if a.get("platform") == "workbuddy"
          and a.get("token") and a.get("uid")]
    if not wb:
        logger.info("未找到 workbuddy 凭据（config.yaml 无 platform=workbuddy 条目）")
        return 1
    logger.info("=" * 56)
    logger.info(f"开始派猫猫旅行，共 {len(wb)} 个 workbuddy 账户")
    logger.info("=" * 56)
    all_ok = True
    for acc in wb:
        token = str(acc.get("token") or "")
        uid = str(acc.get("uid") or "")
        remark = str(acc.get("username") or acc.get("name") or uid[:8])
        ok, msg = _travel_one(token, uid, remark)
        all_ok = all_ok and ok
        mark = "成功" if ok else "失败"
        logger.info(f"[{mark}] [{remark}] {msg}")
    logger.info("-" * 56)
    logger.info(f"旅行状态机完成：{'全部成功' if all_ok else '部分失败'}")
    return 0 if all_ok else 1
