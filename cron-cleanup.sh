#!/data/data/com.termux/files/usr/bin/bash
# cron 触发：定期清理日志与缓存，避免长期累积
# 用法：由 crontab 自动调用，0 3 * * 0（每周日 03:00）

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

export PATH="/data/data/com.termux/files/usr/bin:$PATH"
TS="$(date '+%Y-%m-%d %H:%M:%S')"

echo "[$TS] 清理开始" >> data/cleanup.log

# ---------- 1. 截断日志（保留最后 1000 行） ----------
for log in data/server.log data/cron.log data/cron-travel.log data/cleanup.log; do
    [ -f "$log" ] || continue
    # 保留最后 1000 行，避免无限增长
    tail -n 1000 "$log" > "${log}.tmp" && mv "${log}.tmp" "$log"
done

# ---------- 2. pip 缓存 ----------
pip cache purge 2>/dev/null || rm -rf ~/.cache/pip/* 2>/dev/null || true

# ---------- 3. apt 缓存 ----------
# Termux pkg 无 cache 子命令，用 apt clean（pkg 是 apt 包装器）
apt clean 2>/dev/null || apt-get clean 2>/dev/null || true

# ---------- 4. __pycache__（>7天未访问） ----------
find checkin/ -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ---------- 5. Python 轮转日志旧档（.log.1 ~ .log.30） ----------
# logger.py 的 TimedRotatingFileHandler 已限 backupCount=30，这里兜底删>30天
find data/ -name "checkin.log.*" -mtime +30 -delete 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理完成" >> data/cleanup.log
