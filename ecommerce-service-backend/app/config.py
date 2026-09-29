from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # 全栈统一使用 PostgreSQL（与客服 Agent 同实例、不同库名 commerce）
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://cs:cs_pass_change_me@127.0.0.1:5432/commerce",
    )
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "18081"))

    # 启动时若库为空则写入演示数据（便于课堂演示；置 false 可关闭）
    seed_on_startup: bool = _env_bool("SEED_ON_STARTUP", True)


settings = Settings()
