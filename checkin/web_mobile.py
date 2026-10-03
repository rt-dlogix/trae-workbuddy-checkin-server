"""HTTP 服务（手机端精简版，替代 FastAPI + uvicorn）

用 http.server.ThreadingHTTPServer 实现，零第三方依赖（标准库自带）。
保留电脑端 sync_credentials.py 调用的全部 API 端点 + 新增 /report HTML 简报台。

路由表：
    POST   /api/login                  密码登录（兼容，无密码直返 ok）
    POST   /api/accounts/trae_client   TRAE 客户端凭据上传
    POST   /api/accounts/workbuddy     WorkBuddy 凭据上传
    GET    /api/state                   总览 JSON（账户 + 今日结果）
    POST   /api/checkin                 手动触发签到（简报台按钮）
    DELETE /api/accounts/{name}         删账户（简报台设置按钮）
    GET    /report                      HTML 简报台
    GET    /                            重定向 /report
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import runner
from .report import render_report
from .store import Store, StoreError

logger = logging.getLogger("checkin")

SESSION_COOKIE = "ck_session"
SESSION_MAX_AGE = 30 * 86400  # 30 天


def _session_token(password: str) -> str:
    return hashlib.sha256(f"checkin-server::{password}".encode()).hexdigest()


def _parse_expires(value) -> float | None:
    """expires_at（毫秒时间戳 / ISO 字符串）→ epoch 秒；无法解析返回 None"""
    if value in (None, "", 0):
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        from datetime import datetime, timezone
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    return ts / 1000.0 if ts > 1e11 else ts


def _account_view(acc: dict) -> dict:
    """生成给电脑端 / 简报台用的账户视图"""
    raw_expires = acc.get("expires_at")
    ts = _parse_expires(raw_expires)
    auto_renew = bool(
        acc.get("platform") == "trae" and acc.get("auth_type") != "web" and acc.get("refresh_token")
    )
    return {
        "name": acc.get("name"),
        "platform": acc.get("platform"),
        "auth_type": acc.get("auth_type") or ("web" if acc.get("cookie") else "client"),
        "username": acc.get("username") or acc.get("nickname") or "",
        "user_id": str(acc.get("user_id") or acc.get("uid") or ""),
        "expires_at": raw_expires,
        "expires_ts": ts,
        "expires_in_days": int((ts - time.time()) // 86400) if ts else None,
        "expired": (ts is not None and ts <= time.time()),
        "auto_renew": auto_renew,
        "has_secret": bool(acc.get("cookie") or acc.get("token")),
    }


def _today_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


class MobileHTTPHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器：手写路由分发"""

    # 类级属性，由 run_server 注入
    store: Store = None  # type: ignore[assignment]
    web_password: str = ""

    # ---------- 通用工具 ----------

    def log_message(self, format, *args):
        # 走 checkin logger，不污染 stderr
        logger.debug("HTTP %s - %s", self.address_string(), format % args)

    def _read_json(self) -> dict:
        """读请求体。JSON 返回 dict；表单（application/x-www-form-urlencoded）返回 dict；
        空体或解析失败返回 {}。简报台 form POST 与电脑端 JSON POST 都支持。"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype.split(";")[0]:
            parsed = parse_qs(raw.decode("utf-8", errors="replace"))
            return {k: (v[0] if v else "") for k, v in parsed.items()}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookie(self) -> str:
        cookie_header = self.headers.get("Cookie", "")
        c = SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return ""
        return c.get(SESSION_COOKIE, SimpleCookie.Morsel()).value if SESSION_COOKIE in c else ""

    def _check_auth(self) -> bool:
        """无密码时直通；有密码时校验 cookie"""
        if not self.web_password:
            return True
        return hmac.compare_digest(self._cookie(), _session_token(self.web_password))

    def _set_session_cookie(self) -> bytes:
        morsel = f"{SESSION_COOKIE}={_session_token(self.web_password)}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_MAX_AGE}"
        return morsel.encode("utf-8")

    # ---------- 路由分发 ----------

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "":
            self._redirect("/report")
            return
        if path == "/report":
            self._handle_report()
            return
        if path == "/api/state":
            self._handle_state()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Not Found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            self._handle_login()
            return
        if path == "/api/accounts/trae_client":
            self._handle_upsert_trae_client()
            return
        if path == "/api/accounts/workbuddy":
            self._handle_upsert_workbuddy()
            return
        if path == "/api/checkin":
            self._handle_checkin()
            return
        if path == "/api/history/reset":
            self._handle_history_reset()
            return
        if path.startswith("/api/accounts/") and path.endswith("/delete"):
            name = path[len("/api/accounts/"):-len("/delete")]
            self._handle_delete_account(name)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Not Found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/accounts/"):
            name = path[len("/api/accounts/"):]
            self._handle_delete_account(name)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Not Found"})

    # ---------- 鉴权 ----------

    def _handle_login(self):
        body = self._read_json()
        password = str(body.get("password") or "")
        if not self.web_password:
            self._send_json(HTTPStatus.OK, {"ok": True, "message": "未设置 WEB_PASSWORD，无需登录"})
            return
        if hmac.compare_digest(password, self.web_password):
            payload = b'{"ok": true}'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Set-Cookie", self._set_session_cookie().decode("utf-8"))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "密码错误"})

    # ---------- 总览 ----------

    def _handle_state(self):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        accounts = self.store.accounts()
        today = _today_str()
        history = self.store.read_history(days=1)
        views = [_account_view(a) for a in accounts]
        self._send_json(HTTPStatus.OK, {
            "web_auth_enabled": bool(self.web_password),
            "settings": self.store.settings(),
            "accounts": views,
            "today_results": [r for r in history if r.get("date") == today],
        })

    # ---------- 上传账户 ----------

    def _handle_upsert_trae_client(self):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        body = self._read_json()
        acc = {
            "name": str(body.get("name") or "").strip() or None,
            "platform": "trae",
            "auth_type": "client",
            "token": str(body.get("token") or "").strip(),
            "refresh_token": str(body.get("refresh_token") or "").strip(),
            "expires_at": body.get("expires_at") or "",
            "user_id": str(body.get("user_id") or "").strip(),
            "host": str(body.get("host") or "https://api.trae.cn").strip(),
            "device_id": str(body.get("device_id") or "").strip(),
            "machine_id": str(body.get("machine_id") or "").strip(),
            "ide_version": str(body.get("ide_version") or "").strip(),
            "username": str(body.get("username") or body.get("nickname") or "").strip(),
        }
        if not acc["token"]:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "token 不能为空"})
            return
        try:
            acc = self.store.upsert_account(acc)
        except StoreError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(e)})
            return
        # 异步查询状态（不阻塞响应；失败不影响上传结果）
        try:
            status = runner.query_status(acc, store=self.store)
        except Exception as e:
            status = {"ok": False, "message": f"状态查询失败：{e}"}
        self._send_json(HTTPStatus.OK, {"ok": True, "account": _account_view(acc), "status": status})

    def _handle_upsert_workbuddy(self):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        body = self._read_json()
        raw = str(body.get("raw") or "").strip()
        token = str(body.get("token") or "").strip()
        uid = str(body.get("uid") or "").strip()
        domain = str(body.get("domain") or "").strip()
        expires_at = body.get("expires_at")
        nickname = ""

        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": f"粘贴的内容不是合法 JSON：{e}"})
                return
            auth = data.get("auth") if isinstance(data, dict) else None
            auth = auth if isinstance(auth, dict) else {}
            account_obj = data.get("account") if isinstance(data, dict) else None
            account_obj = account_obj if isinstance(account_obj, dict) else {}
            token = str(auth.get("accessToken") or token)
            uid = str(account_obj.get("uid") or auth.get("uid") or uid)
            domain = str(auth.get("domain") or domain)
            expires_at = auth.get("expiresAt", expires_at)
            local_nick = account_obj.get("nickname")
            if isinstance(local_nick, str) and local_nick.strip():
                nickname = local_nick.strip()

        if not token or not uid:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "缺少 accessToken 或 uid"})
            return
        acc = {
            "name": str(body.get("name") or "").strip() or None,
            "platform": "workbuddy",
            "token": token,
            "uid": uid,
            "domain": domain,
            "expires_at": expires_at,
            "username": str(body.get("username") or body.get("nickname") or nickname or "").strip(),
        }
        try:
            acc = self.store.upsert_account(acc)
        except StoreError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(e)})
            return
        try:
            status = runner.query_status(acc, store=self.store)
        except Exception as e:
            status = {"ok": False, "message": f"状态查询失败：{e}"}
        self._send_json(HTTPStatus.OK, {"ok": True, "account": _account_view(acc), "status": status})

    # ---------- 删账户 ----------

    def _handle_delete_account(self, name: str):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        if not name:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "缺少账户名"})
            return
        if self.store.delete_account(name):
            self._send_json(HTTPStatus.OK, {"ok": True})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": f"账户不存在：{name}"})

    # ---------- 手动签到 ----------

    def _handle_checkin(self):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        body = self._read_json()
        name = str(body.get("name") or "").strip()
        accounts = self.store.accounts()
        if not accounts:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "还没有配置任何账户"})
            return
        if not runner.run_lock.acquire(blocking=False):
            self._send_json(HTTPStatus.CONFLICT, {"ok": False, "message": "有签到任务正在执行，请稍后再试"})
            return
        try:
            if name:
                acc = next((a for a in accounts if a.get("name") == name), None)
                if acc is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": f"账户不存在：{name}"})
                    return
                result = runner.run_account(acc, store=self.store)
                self._send_json(HTTPStatus.OK, {"ok": result.ok, "message": result.message, "credits": result.credits})
            else:
                results = runner.run_all(accounts, store=self.store)
                self._send_json(HTTPStatus.OK, {
                    "ok": all(r.ok for _, r in results),
                    "total": len(results),
                    "failed": sum(1 for _, r in results if not r.ok),
                })
        finally:
            runner.run_lock.release()

    # ---------- 重置历史（保留兼容） ----------

    def _handle_history_reset(self):
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "未登录或会话已失效"})
            return
        body = self._read_json()
        group = str(body.get("group") or "").strip()
        if not group:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "缺少 group"})
            return
        # 简化：按 group 前缀（platform|identity）删除匹配记录
        removed = self.store.delete_history_where(
            lambda r: f"{r.get('platform')}|{r.get('user_key')}" == group
        )
        logger.info(f"重置签到历史：group={group}，已删除 {removed} 条记录")
        self._send_json(HTTPStatus.OK, {"ok": True, "group": group, "removed": removed})

    # ---------- HTML 简报台 ----------

    def _handle_report(self):
        # 简报台本身不强制鉴权（仅本机/内网查看）；如需密码可加 _check_auth
        try:
            html = render_report(self.store)
        except Exception as e:
            logger.exception("生成简报失败")
            self._send_html(HTTPStatus.INTERNAL_SERVER_ERROR, f"<h1>简报生成失败</h1><pre>{e}</pre>")
            return
        self._send_html(HTTPStatus.OK, html)


def run_server(store: Store, host: str = "0.0.0.0", port: int = 8080) -> None:
    """启动 ThreadingHTTPServer，阻塞调用"""
    web_password = os.environ.get("WEB_PASSWORD", "").strip()

    # 启动时合并重复账户（同一平台同一 token 被导入多次）
    try:
        merged = store.dedupe_accounts()
        if merged.get("removed"):
            logger.info(f"启动清理：已合并 {merged['removed']} 个重复账户，现有 {merged['total']} 个")
    except Exception as e:
        logger.warning(f"合并重复账户失败：{e}")

    # 通过子类注入 store 与 password，避免全局变量
    class _Handler(MobileHTTPHandler):
        pass
    _Handler.store = store  # type: ignore[assignment]
    _Handler.web_password = web_password  # type: ignore[assignment]

    server = ThreadingHTTPServer((host, port), _Handler)
    logger.info(f"HTTP 服务已启动：http://{host}:{port}  （密码{'已启用' if web_password else '未设置'}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，关闭服务")
    finally:
        server.server_close()
