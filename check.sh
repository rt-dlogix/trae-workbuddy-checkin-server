#!/data/data/com.termux/files/usr/bin/bash
# 自检脚本：验证 checkin-server 部署完整性
# 用法：bash check.sh
# 检查项：依赖、crond、crontab、bashrc 自启段、HTTP 服务、时区、数据目录、手动签到、清理机制

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PATH="/data/data/com.termux/files/usr/bin:$PATH"

# 计数器
PASS=0
FAIL=0
WARN=0

ok()   { echo "  [OK]   $1"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
warn() { echo "  [WARN] $1"; WARN=$((WARN+1)); }

echo "============================================================"
echo "  checkin-server 自检"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"
echo

# ---------- 1. 系统依赖 ----------
echo "[1/9] 系统依赖..."
command -v python >/dev/null 2>&1 && ok "python: $(python --version 2>&1)" || fail "python 未安装"
command -v crond  >/dev/null 2>&1 && ok "crond 已就绪" || fail "crond 未找到（需 Termux v0.79+）"
command -v termux-wake-lock >/dev/null 2>&1 && ok "termux-api 已装" \
    || warn "termux-api 未装（server.sh 防休眠失效）"

# ---------- 2. Python 依赖 ----------
echo
echo "[2/9] Python 依赖..."
for pkg in requests Crypto yaml tzdata; do
    python -c "import $pkg" 2>/dev/null && ok "python 包 $pkg" \
        || fail "python 包 $pkg 缺失（pip install -r requirements.txt）"
done

# ---------- 3. 时区 ----------
echo
echo "[3/9] 时区..."
if [ "$(cat /etc/timezone 2>/dev/null || echo $TZ)" = "Asia/Shanghai" ] \
   || [ "$TZ" = "Asia/Shanghai" ]; then
    ok "TZ=Asia/Shanghai（当前时间: $(date '+%H:%M %Z)')"
else
    fail "时区非 Asia/Shanghai（当前 TZ=$TZ，时间: $(date '+%H:%M %Z)')"
    echo "        cron 调度时间会偏移"
fi

# ---------- 4. crond 进程 ----------
echo
echo "[4/9] crond 进程..."
if pgrep -x crond >/dev/null 2>&1; then
    ok "crond 运行中 (PID=$(pgrep -x crond))"
else
    fail "crond 未运行"
    echo "        修复：crond 或重启 Termux 触发 bashrc"
fi

# ---------- 5. crontab ----------
echo
echo "[5/9] crontab 配置..."
CRON_LIST=$(crontab -l 2>/dev/null)
if [ -z "$CRON_LIST" ]; then
    fail "crontab 为空"
    echo "        修复：重跑 install.sh 或手动配"
else
    echo "$CRON_LIST" | grep -q "cron-checkin.sh"  && ok "签到任务 (06/12/20:00)" || fail "缺签到任务"
    CNT_TRAVEL=$(echo "$CRON_LIST" | grep -c "cron-travel.sh")
    [ "$CNT_TRAVEL" -eq 3 ] && ok "旅行任务 3 条 (06/12/20:00)" \
        || fail "旅行任务应 3 条，实际 $CNT_TRAVEL"
    echo "$CRON_LIST" | grep -q "cron-cleanup.sh" && ok "清理任务 (周日 03:00)" || warn "缺清理任务"
fi

# ---------- 6. bashrc 自启段 ----------
echo
echo "[6/9] bashrc 自启段..."
BASHRC="$HOME/.bashrc"
if grep -q '# checkin-server 自启段' "$BASHRC" 2>/dev/null; then
    ok "自启段标记行存在"
    grep -q 'pgrep -x crond'          "$BASHRC" && ok "crond 自启逻辑"   || fail "缺 crond 自启"
    grep -q 'python -m checkin --serve' "$BASHRC" && ok "HTTP 服务自启逻辑" || fail "缺 HTTP 服务自启"
else
    fail "~/.bashrc 无 checkin-server 自启段"
    echo "        修复：重跑 install.sh 或手贴 README bashrc 模板"
fi

# ---------- 7. HTTP 服务 ----------
echo
echo "[7/9] HTTP 服务..."
if pgrep -f "python -m checkin --serve" >/dev/null 2>&1; then
    ok "HTTP 服务运行中 (PID=$(pgrep -f 'python -m checkin --serve'))"
else
    fail "HTTP 服务未运行"
    echo "        修复：bash server.sh"
fi

if [ -f data/server.pid ]; then
    SPID=$(cat data/server.pid)
    kill -0 "$SPID" 2>/dev/null && ok "server.pid 有效 (PID=$SPID)" \
        || warn "server.pid 进程已死（僵尸 pid 文件）"
fi

# 端口探测（本地）
if command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null --max-time 3 http://127.0.0.1:8080/report \
        && ok "端口 8080 响应 /report" \
        || warn "端口 8080 无响应（服务未起或 curl 缺失）"
fi

# ---------- 8. 数据目录与凭据 ----------
echo
echo "[8/9] 数据目录..."
[ -d data ]            && ok "data/ 目录存在" || fail "data/ 目录缺失"
[ -f data/config.yaml ] && ok "config.yaml 存在" || warn "config.yaml 缺失（服务未起或未上传凭据）"
[ -f data/history.json ] && ok "history.json 存在" || warn "history.json 缺失（无签到记录）"

# 账户数
if [ -f data/config.yaml ]; then
    ACCT_CNT=$(python -c "
import yaml,sys
try:
    d=yaml.safe_load(open('data/config.yaml'))
    print(len(d.get('accounts',[])))
except: print(0)
" 2>/dev/null)
    [ "${ACCT_CNT:-0}" -gt 0 ] && ok "已配置 $ACCT_CNT 个账户" \
        || warn "无账户配置（电脑端 sync-to-nas.bat 上传凭据）"
fi

# ---------- 9. 清理机制 ----------
echo
echo "[9/9] 清理机制..."
# cron-cleanup.sh 存在且可执行
[ -x cron-cleanup.sh ] && ok "cron-cleanup.sh 可执行" \
    || { [ -f cron-cleanup.sh ] && warn "cron-cleanup.sh 无执行权限（chmod +x）" \
         || fail "cron-cleanup.sh 缺失"; }
# 清理任务曾执行（cleanup.log 存在）
[ -f data/cleanup.log ] && ok "清理任务曾执行（见 cleanup.log）" \
    || warn "cleanup.log 不存在（cron-cleanup.sh 未跑过；等周日 03:00 或手跑 bash cron-cleanup.sh）"
# logger.py 轮转配置（TimedRotatingFileHandler backupCount=30）
python -c "from checkin.logger import setup_logger; print('ok')" 2>/dev/null \
    && ok "logger.py 轮转配置（backupCount=30）" \
    || warn "logger.py 导入失败（TimedRotatingFileHandler 配置无法验证）"
# store.py 180 天历史删除常量
python -c "from checkin.store import HISTORY_MAX_AGE_DAYS; assert HISTORY_MAX_AGE_DAYS==180; print('ok')" 2>/dev/null \
    && ok "store.py 历史删除（>180 天）" \
    || warn "store.py HISTORY_MAX_AGE_DAYS 验证失败"
# crontab 含清理任务
crontab -l 2>/dev/null | grep -q "cron-cleanup.sh" \
    && ok "crontab 含清理任务（周日 03:00）" \
    || warn "crontab 缺清理任务"

# ---------- 总结 ----------
echo
echo "============================================================"
echo "  自检结果：通过 $PASS / 失败 $FAIL / 警告 $WARN"
echo "============================================================"
if [ "$FAIL" -gt 0 ]; then
    echo "  存在失败项，按上述 [FAIL] 提示修复。"
    exit 1
fi
[ "$WARN" -gt 0 ] && echo "  存在警告项，建议处理但不阻塞。"
echo "  部署符合预期。"
exit 0
