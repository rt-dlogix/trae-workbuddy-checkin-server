#!/data/data/com.termux/files/usr/bin/bash
# 停止 checkin-server HTTP 服务
# 用法：bash stop.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -f data/server.pid ]; then
    echo "[WARN] 未找到 data/server.pid，服务可能未运行"
    # 兜底：按进程名杀
    pkill -f "python -m checkin --serve" 2>/dev/null && echo "[OK] 已按进程名清理" || echo "[INFO] 无残留进程"
    termux-wake-unlock 2>/dev/null
    exit 0
fi

PID=$(cat data/server.pid)
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "[OK] 已停止 HTTP 服务 (PID=$PID)"
else
    echo "[INFO] 进程 $PID 已不存在"
fi
rm -f data/server.pid

# 释放 wake-lock
termux-wake-unlock 2>/dev/null || true
echo "[OK] wake-lock 已释放"
