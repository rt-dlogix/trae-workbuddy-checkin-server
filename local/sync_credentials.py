#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本机的 Trae CN / TRAE SOLO CN / WorkBuddy 登录凭据同步到远程自动签到服务（NAS Docker）

单文件版：登录态提取与上传逻辑合并在本文件中，无需额外 .py 文件。

用法（推荐双击同目录的 sync-to-nas.bat，它会自动补装依赖）：
    python sync_credentials.py [服务地址]

服务地址请用命令行参数或环境变量 CHECKIN_SERVER 指定（下面的 DEFAULT_SERVER 只是占位示例）。
如服务设置了 WEB_PASSWORD，会通过环境变量 CHECKIN_WEB_PASSWORD 或交互输入获取。

只导出账户片段（原 extract_credentials.py 的独立功能，不上传）：
    python sync_credentials.py --extract-only                # 输出 extracted_accounts.yaml
    python sync_credentials.py --extract-only -o my.yaml     # 指定输出文件

流程：本机只读提取登录态 → 调用远程 Web API 导入并验证 → 打印结果
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import ipaddress
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    print("缺少依赖：请先执行 pip install requests pycryptodome pyyaml（或双击 sync-to-nas.bat 自动安装）")
    sys.exit(1)

try:
    import requests
    import yaml
except ImportError:
    print("缺少依赖：请先执行 pip install requests pycryptodome pyyaml（或双击 sync-to-nas.bat 自动安装）")
    sys.exit(1)

DEFAULT_SERVER = "http://192.168.x.x:8080"   # 占位示例，实际请用参数 / CHECKIN_SERVER 覆盖


# ============================================================
# 第一部分：本机客户端登录态提取
# ============================================================

# Trae 客户端数据目录名（%APPDATA% / macOS Application Support / ~/.config 下）
TRAE_APP_NAMES = ["Trae CN", "TRAE SOLO CN", "Trae", "TRAE SOLO"]
AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
DC_KEY_RE = re.compile(r"^iCubeAuthInfo://icube-dc:(\d+)$")

# iCube「tc 格式」登录态解密常量（与 Trae 客户端加密格式对应）
SALT_A = bytes([
    82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
    124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
    84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
    8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
])
SALT_B = bytes([
    31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
    96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
    160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
    23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
])


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def mask(s) -> str:
    s = str(s or "")
    return (s[:8] + "...") if s else "(空)"


def candidate_trae_storages() -> list:
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata))
    home = Path.home()
    roots.append(home / "Library" / "Application Support")  # macOS
    roots.append(home / ".config")  # Linux
    out = []
    for root in roots:
        for name in TRAE_APP_NAMES:
            p = root / name / "User" / "globalStorage" / "storage.json"
            if p.exists() and p not in out:
                out.append(p)
    return out


def decrypt_auth(b64_text: str) -> dict:
    """解密 Trae「tc 格式」加密登录串，返回含 token / refreshToken 的 dict"""
    buf = base64.b64decode(b64_text)
    header, rb, enc = buf[:6], buf[6:38], buf[38:]
    if header != bytes([0x74, 0x63, 0x05, 0x10, 0x00, 0x00]):
        raise ValueError("未知的登录态加密格式（header 不匹配）")
    salt = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))
    h = hashlib.sha512(hashlib.sha512(rb).digest() + salt).digest()
    plain = unpad(AES.new(h[:16], AES.MODE_CBC, h[16:32]).decrypt(enc), 16)
    stored, payload = plain[:64], plain[64:]
    if hashlib.sha512(payload).digest() != stored:
        raise ValueError("解密校验失败（SHA-512 不符）")
    return json.loads(payload.decode("utf-8"))


def extract_trae() -> list:
    accounts, seen = [], set()
    for storage_path in candidate_trae_storages():
        try:
            storage = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[跳过] {storage_path}：读取失败（{e}）")
            continue
        enc = storage.get(AUTH_KEY)
        if not enc:
            continue
        try:
            if str(enc).strip().startswith("{"):  # 国际版明文
                auth = json.loads(enc)
            else:
                auth = decrypt_auth(str(enc))
        except Exception as e:
            print(f"[跳过] {storage_path}：解密失败（{e}）")
            continue
        token = auth.get("token")
        if not token or token in seen:
            continue
        seen.add(token)

        device_id = ""
        for k in storage:
            m = DC_KEY_RE.match(k)
            if m:
                device_id = m.group(1)
                break

        accounts.append({
            "name": storage_path.parents[2].name,  # 如 Trae CN
            "platform": "trae",
            "token": token,
            "refresh_token": auth.get("refreshToken", ""),
            "expires_at": auth.get("expiredAt", ""),
            "user_id": str(auth.get("userId", "")),
            "host": auth.get("host") or "https://api.trae.cn",
            "device_id": device_id,
            "machine_id": storage.get("telemetry.machineId", ""),
            "ide_version": storage.get("iCubeLastVersion", ""),
            # 昵称：登录态里自带（服务端也能查到，这里作为导入时的兜底）
            "username": str((auth.get("account") or {}).get("username") or "").strip(),
        })
    return accounts


def workbuddy_auth_dirs() -> list:
    dirs = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    home = Path.home()
    dirs.append(
        home / "Library" / "Application Support"
        / "CodeBuddyExtension" / "Data" / "Public" / "auth"
    )
    return [d for d in dirs if d.is_dir()]


# ---- 新版 WorkBuddy 加密凭据（{"$wbEncrypted": 1, ...}，AES-256-GCM）----
# 加密密钥 = SHA-256(atRestSecretKey)，该密钥随客户端安装内置、仅存在于运行中的
# 客户端进程内存；这里通过扫描 WorkBuddy 进程内存取回后解密字段（仅 Windows）。
WB_SECRET_RE = re.compile(rb'\{"version":1,"atRestSecretKey":"([A-Za-z0-9+/]{43}=)"')


def _wb_lenpref(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _wb_field_aad(key_id: str) -> bytes:
    """对应客户端 at-rest-crypto sym-v1 field 信封的 AAD 构成"""
    return (
        b"WB-AAD\x00" + b"\x01"
        + _wb_lenpref(b"WBEV1") + _wb_lenpref(b"sym-v1")
        + (1).to_bytes(4, "big") + _wb_lenpref(key_id.encode())
        + b"\x02" + b"\x00" + b"\x00"
    )


def wb_decrypt_field(secret_key: bytes, envelope_b64: str) -> str:
    """用 at-rest 密钥解密单个 $wbEncrypted 字段，返回明文字符串"""
    env = json.loads(base64.b64decode(envelope_b64))
    cipher = AES.new(secret_key, AES.MODE_GCM,
                     nonce=base64.b64decode(env["nonce"]), mac_len=16)
    cipher.update(_wb_field_aad(env["keyId"]))
    plain = cipher.decrypt_and_verify(
        base64.b64decode(env["ciphertext"]), base64.b64decode(env["authTag"]))
    return plain.decode("utf-8")


def wb_scan_secret_key():
    """扫描运行中的 WorkBuddy 进程内存，返回 at-rest 解密密钥（不可用时返回 None）"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                        ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p),
                        ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wt.DWORD), ("_a1", wt.DWORD),
                        ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                        ("Protect", wt.DWORD), ("Type", wt.DWORD),
                        ("_a2", wt.DWORD)]

        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(2, 0)
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        pids = []
        if k32.Process32First(snap, ctypes.byref(pe)):
            while True:
                if b"orkBuddy" in pe.szExeFile:
                    pids.append(pe.th32ProcessID)
                if not k32.Process32Next(snap, ctypes.byref(pe)):
                    break
        k32.CloseHandle(snap)
        for pid in pids:
            handle = k32.OpenProcess(0x410, False, pid)  # QUERY_INFO | VM_READ
            if not handle:
                continue
            addr = 0
            secret = None
            while addr < 0x7FFFFFFEFFFF and secret is None:
                mbi = MBI()
                if not k32.VirtualQueryEx(handle, ctypes.c_void_p(addr),
                                          ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    break
                if mbi.State == 0x1000 and mbi.Protect not in (0, 1, 0x20):
                    off = 0
                    while off < mbi.RegionSize:
                        chunk = min(4 << 20, mbi.RegionSize - off)
                        buf = ctypes.create_string_buffer(chunk)
                        got = ctypes.c_size_t(0)
                        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr + off),
                                                     buf, chunk, ctypes.byref(got)):
                            break
                        m = WB_SECRET_RE.search(buf.raw[:got.value])
                        if m:
                            secret = hashlib.sha256(m.group(1)).digest()
                            break
                        off += 4 << 20
                addr += mbi.RegionSize
            k32.CloseHandle(handle)
            if secret:
                return secret
    except Exception:
        return None
    return None


def wb_nickname(account_obj: dict, secret_key: bytes | None = None) -> str:
    """从 .info 的 account 段取昵称（明文直接用；加密值有内存密钥时解密）"""
    value = (account_obj or {}).get("nickname")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict) and value.get("$wbEncrypted") and secret_key:
        try:
            return wb_decrypt_field(secret_key, value["envelope"]).strip()
        except Exception:
            return ""
    return ""


def extract_workbuddy() -> list:
    accounts, seen = [], set()
    for d in workbuddy_auth_dirs():
        for path in sorted(d.glob("*.info")):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[跳过] {path}：读取失败（{e}）")
                continue
            auth = session.get("auth") or {}
            account_obj = session.get("account") or {}
            token = auth.get("accessToken")
            uid = account_obj.get("uid")
            secret_key = None
            if isinstance(token, dict) and token.get("$wbEncrypted"):
                secret_key = wb_scan_secret_key()
                if not secret_key:
                    print(f"[跳过] {path.name}：token 已加密存储且 WorkBuddy 未在运行，无法解密")
                    continue
                try:
                    token = wb_decrypt_field(secret_key, token["envelope"])
                    print(f"[解密] {path.name}：已通过客户端内存密钥解密 accessToken")
                except Exception as e:
                    print(f"[跳过] {path.name}：解密失败（{e}）")
                    continue
            if not token or not uid or token in seen:
                continue
            seen.add(token)
            accounts.append({
                "name": path.stem,
                "platform": "workbuddy",
                "token": token,
                "uid": str(uid),
                "domain": auth.get("domain", ""),
                "expires_at": auth.get("expiresAt"),
                "username": wb_nickname(account_obj, secret_key),
            })
    return accounts


# ============================================================
# 第二部分：上传到远程自动签到服务
# ============================================================

def to_epoch(value) -> float:
    """统一转成可比较的 epoch 秒（用于同账号去重时比较新旧）"""
    if value in (None, "", 0):
        return 0.0
    # 毫秒时间戳
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        pass
    # ISO 字符串
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def collect_trae() -> list:
    """提取并按 user_id 去重（同一账号多客户端只保留 expires_at 最新的）"""
    accounts = extract_trae()
    by_uid = {}
    for acc in accounts:
        uid = acc.get("user_id") or id(acc)
        prev = by_uid.get(uid)
        if prev is None or to_epoch(acc.get("expires_at")) > to_epoch(prev.get("expires_at")):
            by_uid[uid] = acc
        else:
            log(f"跳过 [{acc['name']}]：与 [{prev['name']}] 是同一账号（user_id 相同），保留更新的登录态")
    return list(by_uid.values())


def wb_name(stem: str, uid: str) -> str:
    """客户端凭据文件名可能是超长的时间戳串（如
    workbuddy-desktop.2026-09-09T16-02-15-635Z.13132.cac3641e-...），
    直接当账户名会在控制台和历史里刷屏；过长时退化为 workbuddy-<uid 前 8 位>。
    远端服务会按 uid 合并到同一账户（保留原有名称），不会产生重复账户。"""
    stem = (stem or "").strip()
    if stem and len(stem) <= 32:
        return stem
    return f"workbuddy-{(uid or '')[:8]}"


def collect_workbuddy() -> list:
    """提取 WorkBuddy 凭据。新版客户端会把 token 加密存储（$wbEncrypted），
    若 WorkBuddy 正在运行则通过其内存中的安装密钥解密后上传；
    同一账号（uid 相同）只保留有效期最长的一份。"""
    by_uid = {}

    def expiry(entry):
        payload = entry["payload"]
        if "raw" in payload:
            return to_epoch((payload["raw"].get("auth") or {}).get("expiresAt"))
        return to_epoch(payload.get("expires_at"))

    for d in workbuddy_auth_dirs():
        for path in sorted(d.glob("*.info")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                log(f"[跳过] WorkBuddy {path.name}：读取失败（{e}）")
                continue
            auth = raw.get("auth") or {}
            uid = (raw.get("account") or {}).get("uid")
            tok = auth.get("accessToken")
            if not tok or not uid:
                log(f"[跳过] WorkBuddy {path.name}：缺少 accessToken / uid")
                continue
            if isinstance(tok, dict) and tok.get("$wbEncrypted"):
                secret_key = wb_scan_secret_key()
                if not secret_key:
                    log(f"跳过 [{path.stem}]：token 已加密存储，且 WorkBuddy 客户端未在运行、无法解密")
                    continue
                try:
                    token = wb_decrypt_field(secret_key, tok["envelope"])
                except Exception as e:
                    log(f"[跳过] WorkBuddy {path.name}：解密失败（{e}）")
                    continue
                log(f"[{path.stem}]：加密凭据已通过客户端内存密钥解密")
                entry = {"name": wb_name(path.stem, uid), "payload": {
                    "name": wb_name(path.stem, uid), "token": token, "uid": str(uid),
                    "domain": auth.get("domain", ""), "expires_at": auth.get("expiresAt"),
                    "username": wb_nickname(raw.get("account") or {}, secret_key),
                }}
            else:
                entry = {"name": wb_name(path.stem, uid),
                         "payload": {"name": wb_name(path.stem, uid), "raw": raw}}
            prev = by_uid.get(uid)
            if prev is None or expiry(entry) > expiry(prev):
                by_uid[uid] = entry
            else:
                log(f"跳过 [{path.stem}]：与 [{prev['name']}] 是同一账号（uid 相同），保留有效期更长的一份")
    return list(by_uid.values())


def is_lan(base: str) -> bool:
    """目标是不是内网地址（NAS 一般就是）。

    本机若设了 http_proxy / https_proxy（公司代理、抓包工具、容器网关），
    requests 会把内网请求也塞给代理，代理对未知主机返回 404，
    表现为「导入失败：Not Found」——非常难查。内网请求一律绕过系统代理。
    强制走代理时设 CHECKIN_USE_PROXY=1。
    """
    host = (urlparse(base).hostname or "").strip()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 裸主机名 / mDNS 名（nas、nas.local）都当内网
        return "." not in host or host.endswith((".local", ".lan", ".home", ".internal"))
    return ip.is_private or ip.is_loopback or ip.is_link_local


def connect_server(base: str) -> requests.Session:
    base = base.rstrip("/")
    session = requests.Session()
    if not os.environ.get("CHECKIN_USE_PROXY") and is_lan(base):
        session.trust_env = False
        log("目标为内网地址，已绕过系统代理（http_proxy/https_proxy）")
    password = os.environ.get("CHECKIN_WEB_PASSWORD", "")
    # 先探测是否启用了密码
    try:
        r = session.get(f"{base}/api/state", timeout=10)
    except requests.RequestException as e:
        raise SystemExit(f"[错误] 无法连接服务 {base}：{e}")
    if r.status_code == 401:
        if not password:
            password = getpass.getpass("服务已启用密码保护，请输入 WEB_PASSWORD：")
        r = session.post(f"{base}/api/login", json={"password": password}, timeout=10)
        if r.status_code != 200:
            raise SystemExit("[错误] 密码错误，同步中止")
    return session


def upload(session: requests.Session, base: str, path: str, payload: dict) -> dict:
    r = session.post(f"{base}{path}", json=payload, timeout=60)
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "detail": f"HTTP {r.status_code}"}


def sync_main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHECKIN_SERVER", DEFAULT_SERVER)
    log(f"目标服务：{base}")

    log("正在提取本机 Trae 客户端登录态 ...")
    trae = collect_trae()
    log("正在提取本机 WorkBuddy 客户端登录态 ...")
    workbuddy = collect_workbuddy()

    if not trae and not workbuddy:
        print("未在本机找到任何登录态。请先在本机安装并登录 Trae CN / TRAE SOLO CN / WorkBuddy 客户端。")
        return 1

    session = connect_server(base)

    ok_count = 0
    total = len(trae) + len(workbuddy)

    for acc in trae:
        name = acc.get("name") or "trae"
        log(f"上传 TRAE 客户端凭据 [{name}]（token={mask(acc.get('token'))}）...")
        resp = upload(session, base, "/api/accounts/trae_client", {
            "name": name,
            "token": acc.get("token", ""),
            "refresh_token": acc.get("refresh_token", ""),
            "expires_at": acc.get("expires_at", ""),
            "user_id": acc.get("user_id", ""),
            "host": acc.get("host", ""),
            "device_id": acc.get("device_id", ""),
            "machine_id": acc.get("machine_id", ""),
            "ide_version": acc.get("ide_version", ""),
            "username": acc.get("username", ""),
        })
        status = resp.get("status") or {}
        if resp.get("ok"):
            ok_count += 1
            if status.get("ok"):
                who = status.get("nickname") or acc.get("username") or "未知用户"
                log(f"  -> 导入成功（{who}），登录态有效，当前余额 {status.get('credits')}")
            else:
                log(f"  -> 已导入，但状态查询失败：{status.get('message')}")
        else:
            log(f"  -> 导入失败：{resp.get('detail') or resp}")

    for wb in workbuddy:
        log(f"上传 WorkBuddy 凭据 [{wb['name']}] ...")
        resp = upload(session, base, "/api/accounts/workbuddy", wb["payload"])
        status = resp.get("status") or {}
        if resp.get("ok"):
            ok_count += 1
            if status.get("ok"):
                who = status.get("nickname") or wb["payload"].get("username") or "未知用户"
                log(f"  -> 导入成功（{who}），登录态有效，当前余额 {status.get('credits')}")
            else:
                log(f"  -> 已导入，但状态查询失败：{status.get('message')}")
        else:
            log(f"  -> 导入失败：{resp.get('detail') or resp}")

    print("-" * 50)
    if ok_count == total:
        log(f"同步完成：{ok_count}/{total} 个账户已导入远端服务")
        return 0
    log(f"同步完成，但有 {total - ok_count} 个失败")
    return 1


# ============================================================
# 第三部分：命令行入口
# ============================================================

def extract_main() -> int:
    """只把登录态导出成 config.yaml 账户片段，不上传"""
    parser = argparse.ArgumentParser(
        description="从本机已登录的 Trae / WorkBuddy 客户端提取登录态，生成 config.yaml 账户片段。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-o", "--out", default="extracted_accounts.yaml",
        help="输出文件（默认 extracted_accounts.yaml）",
    )
    args = parser.parse_args()

    print("正在扫描 Trae 客户端登录态 ...")
    trae = extract_trae()
    print("正在扫描 WorkBuddy 客户端登录态 ...")
    wb = extract_workbuddy()

    accounts = trae + wb
    if not accounts:
        print("\n未找到任何登录态。请确认：")
        print("  1. 已安装并登录 Trae CN / TRAE SOLO CN 客户端")
        print("  2. 已安装并登录 WorkBuddy 客户端")
        return 1

    header = (
        f"# 由 sync_credentials.py --extract-only 于 {datetime.now():%Y-%m-%d %H:%M:%S} 生成\n"
        "# 将 accounts 列表中的条目合并到 data/config.yaml 的 accounts 下即可\n"
        "# 注意：本文件包含账户凭据，请勿提交到版本库或分享给他人\n"
    )
    text = yaml.safe_dump({"accounts": accounts}, allow_unicode=True, sort_keys=False)
    Path(args.out).write_text(header + text, encoding="utf-8")

    print(f"\n共提取 {len(accounts)} 个账户，已写入 {args.out}")
    for a in accounts:
        print(
            f"  - [{a['platform']}] {a['name']}  昵称={a.get('username') or '-'}  "
            f"token={mask(a['token'])}  expires_at={a.get('expires_at')}"
        )
    print(f"\n下一步：把 {args.out} 中的账户条目合并到 data/config.yaml，然后启动容器。")
    return 0


if __name__ == "__main__":
    if "--extract-only" in sys.argv:
        sys.argv.remove("--extract-only")
        sys.exit(extract_main())
    sys.exit(sync_main())
