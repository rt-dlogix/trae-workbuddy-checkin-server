"""HTML 简报台生成（手机端精简版，零前端依赖）

读取 store 生成自包含 HTML 字符串，由 web_mobile 的 /report 端点返回。
"""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from pathlib import Path


def _fmt_expires(acc: dict) -> str:
    """凭据有效期：剩余天数 / 已过期 / 无需关注"""
    raw = acc.get("expires_at")
    if raw in (None, "", 0):
        return '<span class="muted">—</span>'
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return html.escape(str(raw))
    if ts > 1e11:
        ts = ts / 1000.0
    now = time.time()
    auto_renew = bool(
        acc.get("platform") == "trae" and acc.get("refresh_token")
    )
    if ts <= now:
        return '<span class="expires expired">已过期</span>' + ('（可自动续期）' if auto_renew else "")
    days = int((ts - now) // 86400)
    cls = "expired" if days <= 3 else ("warn" if days <= 7 else "ok")
    label = f'<span class="expires {cls}">剩余 {days} 天</span>'
    if auto_renew:
        label += ' <span class="muted">(自动续期)</span>'
    return label


def _today_results_map(history: list) -> dict:
    """key=account name → 最近一次今日签到记录"""
    today = datetime.now().strftime("%Y-%m-%d")
    out: dict = {}
    for r in history:
        if r.get("date") != today:
            continue
        name = r.get("name") or ""
        if name not in out or float(r.get("ts") or 0) > float(out[name].get("ts") or 0):
            out[name] = r
    return out


def _render_accounts_table(accounts: list, history: list) -> str:
    today_map = _today_results_map(history)
    rows = []
    for acc in accounts:
        name = acc.get("name") or ""
        platform = acc.get("platform") or ""
        username = acc.get("username") or acc.get("nickname") or "—"
        rec = today_map.get(name, {})
        ok = rec.get("ok")
        if ok is True:
            status_cls = "ok"
            status_text = "✓ 已签到"
            if rec.get("claimed") and rec.get("credits") is not None:
                status_text += f"（+{rec.get('credits')}）"
        elif ok is False:
            status_cls = "fail"
            status_text = "✗ " + html.escape(str(rec.get("message") or "失败")[:40])
        else:
            status_cls = "idle"
            status_text = "未执行"
        expires = _fmt_expires(acc)
        platform_badge = {"trae": "trae", "workbuddy": "workbuddy"}.get(platform, platform or "unknown")
        rows.append(f"""
        <tr>
          <td class="cell-main"><span class="dot {status_cls}"></span><strong>{html.escape(username)}</strong></td>
          <td><span class="badge badge-{platform_badge}">{html.escape(platform or "—")}</span></td>
          <td class="status {status_cls}">{status_text}</td>
          <td>{expires}</td>
          <td class="cell-actions">
            <form method="POST" action="/api/checkin" class="form-inline">
              <input type="hidden" name="name" value="{html.escape(name)}">
              <button type="submit" class="btn btn-checkin">签到</button>
            </form>
            <form method="POST" action="/api/accounts/{html.escape(name)}/delete" class="form-inline"
                  onsubmit="return confirm('确认删除账户 {html.escape(username)}？')">
              <button type="submit" class="btn btn-delete">删除</button>
            </form>
          </td>
        </tr>""")
    if not rows:
        return '<div class="empty">暂无账户。请先在电脑端运行 sync-to-nas.bat 上传凭据。</div>'
    return f"""
    <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>账户</th>
          <th>平台</th>
          <th>今日结果</th>
          <th>凭据有效期</th>
          <th class="th-right">操作</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}
      </tbody>
    </table>
    </div>"""


def _render_history_section(history: list) -> str:
    """最近 7 天历史记录（按时间倒序，最多 50 条）"""
    history = sorted(history, key=lambda r: float(r.get("ts") or 0), reverse=True)[:50]
    if not history:
        return '<div class="empty">暂无历史记录。</div>'
    rows = []
    for r in history:
        date = r.get("date") or ""
        time_str = r.get("time") or ""
        ok = r.get("ok")
        mark = "✓" if ok else "✗"
        cls = "ok" if ok else "fail"
        name = html.escape(str(r.get("username") or r.get("name") or ""))
        platform = html.escape(str(r.get("platform") or ""))
        message = html.escape(str(r.get("message") or "")[:60])
        credits = r.get("credits")
        credits_str = f'+{credits}' if (r.get("claimed") and credits is not None) else "—"
        rows.append(f"""
        <tr>
          <td class="cell-time">{date}<br><span class="time-sub">{time_str}</span></td>
          <td><strong>{name}</strong></td>
          <td><span class="badge badge-{platform}">{platform or "—"}</span></td>
          <td class="status {cls}">{mark} {message}</td>
          <td class="cell-credits">{credits_str}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>时间</th>
          <th>账户</th>
          <th>平台</th>
          <th>结果</th>
          <th class="th-right">积分</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}
      </tbody>
    </table>
    </div>"""


_CSS = """
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --text: #1a202c;
  --text-2: #4a5568;
  --muted: #94a3b8;
  --border: #e2e8f0;
  --ok: #16a34a;
  --fail: #dc2626;
  --warn: #ea580c;
  --accent: #16a34a;
  --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-2: #162032;
    --text: #f1f5f9;
    --text-2: #cbd5e1;
    --muted: #64748b;
    --border: #334155;
    --ok: #4ade80;
    --fail: #f87171;
    --warn: #fb923c;
    --accent: #4ade80;
    --shadow: 0 1px 3px rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif;
       max-width: 960px; margin: 0 auto; padding: 16px; background: var(--bg);
       color: var(--text); line-height: 1.5; }
header { padding: 16px 0 8px; }
h1 { font-size: 22px; font-weight: 600; margin: 0; letter-spacing: -.02em; }
.meta { color: var(--muted); font-size: 12px; margin: 4px 0 0; }

.summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.card { background: var(--surface); padding: 14px 18px; border-radius: 10px;
        box-shadow: var(--shadow); flex: 1; min-width: 130px; text-align: center;
        border: 1px solid var(--border); }
.card .num { font-size: 26px; font-weight: 700; color: var(--accent); line-height: 1.2; }
.card .num.warn { color: var(--warn); }
.card .label { font-size: 12px; color: var(--muted); margin-top: 4px; }

.section { margin-top: 24px; }
h2 { font-size: 15px; font-weight: 600; color: var(--text-2); margin: 0 0 10px;
     display: flex; align-items: center; gap: 8px; }
h2::before { content: ""; width: 3px; height: 14px; background: var(--accent);
            border-radius: 2px; }

.table-wrap { overflow-x: auto; background: var(--surface); border-radius: 10px;
              border: 1px solid var(--border); box-shadow: var(--shadow); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { background: var(--surface-2); padding: 10px 12px; text-align: left;
           font-weight: 600; color: var(--text-2); border-bottom: 1px solid var(--border);
           white-space: nowrap; }
tbody td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--surface-2); }
.th-right { text-align: right; }
.cell-main { display: flex; align-items: center; gap: 8px; }
.cell-time { white-space: nowrap; color: var(--text-2); }
.time-sub { color: var(--muted); font-size: 11px; }
.cell-credits { font-weight: 600; color: var(--ok); }

.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
.dot.ok { background: var(--ok); }
.dot.fail { background: var(--fail); }
.dot.idle { background: var(--muted); }

.badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
         font-size: 11px; font-weight: 600; line-height: 1.4; }
.badge-trae { background: rgba(22,163,74,.12); color: var(--ok); }
.badge-workbuddy { background: rgba(234,88,12,.12); color: var(--warn); }
.badge-unknown { background: var(--surface-2); color: var(--muted); }

.status { font-weight: 500; }
.status.ok { color: var(--ok); }
.status.fail { color: var(--fail); }
.status.idle { color: var(--muted); }

.expires { font-weight: 600; }
.expires.ok { color: var(--ok); }
.expires.warn { color: var(--warn); }
.expires.expired { color: var(--fail); }

.muted { color: var(--muted); font-weight: 400; font-size: 12px; }

.btn { font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid;
       cursor: pointer; font-weight: 500; transition: all .15s; }
.btn-checkin { background: var(--accent); color: white; border-color: transparent; }
.btn-checkin:hover { filter: brightness(1.1); }
.btn-delete { background: transparent; color: var(--fail); border-color: var(--fail); }
.btn-delete:hover { background: var(--fail); color: white; }
.btn-lg { font-size: 14px; padding: 8px 18px; }
.form-inline { display: inline; margin-right: 6px; }
.cell-actions { white-space: nowrap; }

.empty { background: var(--surface); border: 1px dashed var(--border); padding: 24px;
        text-align: center; color: var(--muted); border-radius: 10px; }

footer { margin-top: 32px; padding: 16px; font-size: 11px; color: var(--muted);
         text-align: center; }
footer a { color: var(--accent); text-decoration: none; }
footer a:hover { text-decoration: underline; }

@media (max-width: 640px) {
  body { padding: 12px; }
  .summary { flex-direction: column; }
  thead th, tbody td { padding: 8px 10px; }
}
"""

_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>签到简报</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>签到简报</h1>
    <p class="meta">更新时间：{today} · 自动刷新 5 分钟</p>
  </header>

  <div class="summary">
    <div class="card"><div class="num">{total_accounts}</div><div class="label">账户总数</div></div>
    <div class="card"><div class="num{ok_num_cls}">{today_count}</div><div class="label">今日已签到</div></div>
    <div class="card"><div class="num warn">{week_success}</div><div class="label">近 7 天成功</div></div>
    <div class="card">
      <div>
        <form method="POST" action="/api/checkin">
          <button type="submit" class="btn btn-checkin btn-lg">全部签到</button>
        </form>
      </div>
      <div class="label">手动触发</div>
    </div>
  </div>

  <div class="section">
    <h2>账户状态</h2>
    {accounts_table}
  </div>

  <div class="section">
    <h2>最近 7 天记录</h2>
    {history_section}
  </div>

  <footer>
    checkin-server · 手机端签到服务 ·
    <a href="/report">刷新</a>
  </footer>

  <script>setTimeout(function(){{location.reload()}},300000);</script>
</body>
</html>"""


def render_report(store) -> str:
    """生成自包含 HTML 简报页"""
    accounts = store.accounts()
    history = store.read_history(days=7)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    accounts_table = _render_accounts_table(accounts, history)
    history_section = _render_history_section(history)

    today_date = today.split()[0]
    today_count = sum(
        1 for a in accounts
        if any(r.get("date") == today_date and r.get("name") == a.get("name") and r.get("ok")
               for r in history)
    )
    total_accounts = len(accounts)
    week_success = sum(1 for r in history if r.get("ok"))
    ok_num_cls = "" if today_count == 0 else ""

    return _PAGE.format(
        css=_CSS,
        today=today,
        total_accounts=total_accounts,
        today_count=today_count,
        week_success=week_success,
        ok_num_cls=ok_num_cls,
        accounts_table=accounts_table,
        history_section=history_section,
    )
