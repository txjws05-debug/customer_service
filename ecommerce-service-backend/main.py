#!/usr/bin/env python3
"""Atguigu 电商业务服务启动脚本。

启动时自动完成建表与演示数据初始化（可用 SEED_ON_STARTUP=false 关闭），
因此容器启动后无需手工导入任何 SQL 脚本。
"""

from __future__ import annotations

import logging
import os

import uvicorn

from app.config import settings
from app.init_data import create_tables, ensure_columns, seed_if_empty
from app.seed_shop import seed_shop_if_empty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("ecommerce.main")


def bootstrap() -> None:
    """建表 + 轻量迁移 + 演示数据初始化。"""
    logger.info("正在初始化数据库: %s", settings.database_url.split("@")[-1])
    create_tables()
    # 已有库需要补新列（create_all 不会改已存在的表）
    ensure_columns()
    if settings.seed_on_startup:
        # 全量演示数据（仅空库）
        seed_if_empty()
        # 交易域增量数据（已有库也能补种，幂等）
        seed_shop_if_empty()


def main() -> None:
    bootstrap()

    # 生产环境（容器内）关闭热重载；本地开发可用 APP_RELOAD=true 打开
    reload_enabled = os.getenv("APP_RELOAD", "false").lower() == "true"

    logger.info("电商业务服务启动中 http://%s:%s", settings.app_host, settings.app_port)
    logger.info("API 文档 http://%s:%s/docs", settings.app_host, settings.app_port)

    uvicorn.run(
        "app.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=reload_enabled,
        log_level="info",
    )


if __name__ == "__main__":
    main()
