#!/data/data/com.termux/files/usr/bin/bash
# 启动 checkin-server HTTP 服务（替代 Docker 容器，常驻）
# 用法：bash server.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 防 Termux 休眠杀进程
termux-wake-lock 2>/dev/null || echo "[WARN] termux-wake-lock 未生效（termux-api 未装？）"

# 默认绑 0.0.0.0:8080，电脑端可访问
# 如需密码：export WEB_PASSWORD="your-password" 后再启动
mkdir -p data

# 后台启动 HTTP 服务
# 用 setsid + exec 确保子进程 PID = $!（避免 nohup 包装进程退出导致 pid 文件失效）
nohup setsid python -m checkin --serve \
    --data-dir "$HERE/data" \
    --host 0.0.0.0 \
    --port 8080 \
    >> data/server.log 2>&1 &

PID=$!
# 等进程起来，校验 PID 存活；失效则回退到 pgrep 取真实 python PID
sleep 1
if ! kill -0 "$PID" 2>/dev/null; then
    PID=$(pgrep -f "python -m checkin --serve" | head -1)
fi
echo $PID > data/server.pid
echo "[OK] HTTP 服务已启动 (PID=$PID)"
echo "     监听：http://0.0.0.0:8080"
echo "     日志：$HERE/data/server.log"
echo "     停止：bash stop.sh"
echo
echo "电脑端访问简报台：http://手机IP:8080/report"
