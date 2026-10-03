#!/data/data/com.termux/files/usr/bin/bash
# cron 触发：执行一轮签到（06:00 / 12:00 / 20:00）
# 用法：由 crontab 自动调用，0 6,12,20 * * *
#
# 三次触发与 WorkBuddy 旅行同步，作为兜底机制：
#   - 06:00  主签到，正常应成功
#   - 12:00  兜底：若 06:00 因网络抖动/服务未就绪漏签
#   - 20:00  兜底：若上午两次都漏（罕见，应对长时间断网）
#
# 签到本身完全幂等：platform 层检测「今日已签到」直接返回 claimed=False，
# runner._record 对未领取的调用不写 credits，历史统计不会重复累加。
#
# 防干扰机制：
#   - termux-wake-lock 防止执行期间手机休眠
#   - 检查 crond 存活，未启动则补启动（应对 Termux 重启后未拉起）
#   - 失败自动重试一次（应对网络抖动/服务未就绪）
#   - 重试间隔 60s，给对端服务留启动窗口

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# 确保 cron 环境能找到 python
export PATH="/data/data/com.termux/files/usr/bin:$PATH"

# 保持屏幕/系统不进入休眠
termux-wake-lock 2>/dev/null || echo "[WARN] wake-lock 未生效（termux-api 未装？）"

# 检查 crond 是否存活（应对 Termux 重启后未拉起 cron 调度的情况）
if ! pgrep -x crond >/dev/null 2>&1; then
    crond 2>/dev/null && echo "[$(date '+%Y-%m-%d %H:%M:%S')] crond 已补启动" >> data/cron.log
fi

# 第一轮执行
python -m checkin --once --data-dir "$HERE/data" >> data/cron.log 2>&1
RC=$?

# 失败重试一次（60s 后），应对网络抖动或服务未就绪
if [ "$RC" -ne 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 签到失败 rc=$RC，60s 后重试" >> data/cron.log
    sleep 60
    python -m checkin --once --data-dir "$HERE/data" >> data/cron.log 2>&1
    RC=$?
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 签到轮结束 rc=$RC" >> data/cron.log

# 释放 wake-lock
termux-wake-unlock 2>/dev/null || true
