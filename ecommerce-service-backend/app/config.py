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

    # 商品读路径的缓存（可选）：不配置就等同「没有缓存」，全部直连 PostgreSQL。
    # 注意：PostgreSQL 始终是唯一事实来源 —— 缓存只加速读、绝不承接写，
    # 而且库存这类强一致字段永远不进缓存（见 app/cache.py 的说明）。
    redis_url: str | None = os.getenv("REDIS_URL")

    # 启动时若库为空则写入演示数据（便于课堂演示；置 false 可关闭）
    seed_on_startup: bool = _env_bool("SEED_ON_STARTUP", True)

    # ---------------------------------------------------------- 接入鉴权
    # off：不校验（默认，与改造前完全一致）；warn：只记日志放行；on：强制
    # 部署环境：prod 时禁止把鉴权关掉（见 app.py 启动校验）
    app_env: str = os.getenv("APP_ENV", "dev").strip().lower()
    auth_enforce: str = os.getenv("AUTH_ENFORCE", "off").strip().lower()

    # Agent 调中台用的服务令牌；为空时服务身份永远匹配不上（等价于没开）
    service_token: str = os.getenv("SERVICE_TOKEN", "")

    # 商家后台的静态令牌，不引入角色体系，省掉跨服务的角色同步
    operator_token: str = os.getenv("OPERATOR_TOKEN", "")

    # 与客服 Agent 共用同一个密钥，只做校验不做签发
    jwt_secret: str = os.getenv("JWT_SECRET_KEY", "")

    # 生产环境默认关闭 /docs，避免把全部接口形状暴露在公网
    expose_docs: bool = _env_bool("EXPOSE_DOCS", True)

    # /metrics 的访问令牌：为空则不校验（仅限内网）。指标会暴露路径、错误率、
    # 耗时分布，等于系统的运行画像，不该裸奔。
    metrics_token: str = os.getenv("METRICS_TOKEN", "").strip()


settings = Settings()
