# checkin-server 服务端镜像
# 仅含服务端（HTTP + cron 调度）；电脑端 sync 工具不入镜像
FROM python:3.12-slim

# cron 按此时区调度（签到 06:00/12:00/20:00）
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends tzdata cron \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY checkin/ ./checkin/

# cron 调度表 + 启动入口
COPY docker/crontab /app/crontab
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/data

VOLUME ["/app/data"]
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
