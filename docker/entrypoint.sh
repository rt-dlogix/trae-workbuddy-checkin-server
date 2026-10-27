#!/bin/sh
# 容器入口：后台 crond（签到/旅行调度）+ 前台 HTTP 服务（日志走 docker logs）
set -e

# 加载 root 用户级 crontab（/app/crontab 格式：不带 user 字段）
crontab /app/crontab

# crond 后台运行
cron

# 前台运行 HTTP 服务；host/port 可用环境变量覆盖
exec python -m checkin --serve \
    --data-dir /app/data \
    --host "${SERVE_HOST:-0.0.0.0}" \
    --port "${SERVE_PORT:-8080}"
