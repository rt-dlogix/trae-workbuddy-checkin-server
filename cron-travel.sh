#!/data/data/com.termux/files/usr/bin/bash
# cron 触发：执行 WorkBuddy 派猫猫旅行状态机（06:00 / 12:00 / 20:00）
# 用法：由 crontab 自动调用，0 6,12,20 * * *
#
# 防干扰机制：
#   - termux-wake-lock 防止执行期间手机休眠
#   - 检查 crond 存活，未启动则补启动
#   - 失败自动重试一次（应对网络抖动/服务未就绪）
#   - 重试间隔 60s，给对端服务留启动窗口

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

export PATH="/data/data/com.termux/files/usr/bin:$PATH"

# 保持屏幕/系统不进入休眠
termux-wake-lock 2>/dev/null || echo "[WARN] wake-lock 未生效（termux-api 未装？）"

# 检查 crond 是否存活
if ! pgrep -x crond >/dev/null 2>&1; then
    crond 2>/dev/null && echo "[$(date '+%Y-%m-%d %H:%M:%S')] crond 已补启动" >> data/cron-travel.log
fi

# 第一轮执行
python -m checkin --travel --data-dir "$HERE/data" >> data/cron-travel.log 2>&1
RC=$?

# 失败重试一次（60s 后）
if [ "$RC" -ne 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 旅行失败 rc=$RC，60s 后重试" >> data/cron-travel.log
    sleep 60
    python -m checkin --travel --data-dir "$HERE/data" >> data/cron-travel.log 2>&1
    RC=$?
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 旅行状态机轮结束 rc=$RC" >> data/cron-travel.log

# 释放 wake-lock
termux-wake-unlock 2>/dev/null || true
