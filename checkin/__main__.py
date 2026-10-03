"""命令行入口（手机端 Termux 精简版）

用法：
    python -m checkin --serve           # 启动 HTTP 服务（替代 Docker 容器，常驻）
    python -m checkin --once            # 执行一轮签到后退出（cron 调度用）
    python -m checkin --travel          # 执行 WorkBuddy 派猫猫旅行状态机
    python -m checkin --data-dir /path  # 指定数据目录（默认 data）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .logger import setup_logger
from .store import Store


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="checkin", description="TRAE / WorkBuddy 自动签到（手机端）"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="执行一轮签到后退出（cron 06:00/12:00/20:00 调度用）",
    )
    parser.add_argument(
        "--travel",
        action="store_true",
        help="执行 WorkBuddy 派猫猫旅行状态机（cron 06:00/12:00/20:00 用）",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="启动 HTTP 服务（常驻模式，替代 Docker 容器）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("CHECKIN_DATA_DIR", "data")),
        help="数据目录（默认 data，包含 config.yaml / history.json / checkin.log）",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("CHECKIN_WEB_HOST", "0.0.0.0"),
        help="HTTP 服务监听地址（默认 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("CHECKIN_WEB_PORT", "8080")),
        help="HTTP 服务监听端口（默认 8080）",
    )
    args = parser.parse_args()

    setup_logger(args.data_dir / "checkin.log")
    logger = logging.getLogger("checkin")
    store = Store(args.data_dir)

    # 默认行为：启动 HTTP 服务（与 Docker CMD 等价）
    if not args.once and not args.travel and not args.serve:
        args.serve = True

    if args.once:
        from . import runner
        accounts = store.accounts()
        if not accounts:
            logger.error("还没有配置任何账户，请先启动服务并通过电脑端上传")
            return 2
        results = runner.run_all(accounts, store=store)
        return 0 if all(r.ok for _, r in results) else 1

    if args.travel:
        from .travel import run_travel
        return run_travel(store)

    if args.serve:
        from .web_mobile import run_server
        logger.info(f"启动 HTTP 服务：http://{args.host}:{args.port}  （数据目录：{args.data_dir}）")
        run_server(store, host=args.host, port=args.port)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
