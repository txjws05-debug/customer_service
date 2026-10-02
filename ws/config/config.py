import logging
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parents[2] / '.env'


class Settings(BaseSettings):
    # LLM
    llm_api_key: str
    llm_model: str
    llm_base_url: str

    # 数据库
    database_url: str

    # 商城 API
    commerce_api_base_url: str

    # JWT：本地兜底默认值，推荐通过 .env / 环境变量覆盖
    jwt_secret_key: str = "customer-service-dev-secret-please-change"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # 服务器
    app_host: str
    app_port: int

    # ---------- RAG 向量检索 ----------
    # embedding 走 OpenAI 兼容的 /embeddings 接口（硅基流动、阿里云百炼、OpenAI 等都可用）。
    # 三项都不配置时自动退化为「内置本地词法向量」：零依赖、离线可用，
    # 但只按字面重合度检索，没有语义泛化能力。生产建议配一个真模型。
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    # 向量维度。留空 = 自动探测（API 后端第一次调用时问模型要），
    # 本地后端留空则用 512。只有想强制校验时才需要填：
    # 填了却和模型实际输出不一致，启动时会明确报错。
    embedding_dim: int | None = None

    # 检索参数：向量召回候选数、最终返回条数、低于该分数视为「没检索到」
    # min_score 是「垃圾地板」而不是「精度阈值」：意图识别已经先筛过一轮，
    # 能走到检索的基本都是业务问题。本地词法向量下口语化改写分数明显偏低
    # （实测「钱什么时候能退回来」≈0.08，而无关问题的地板在 0.05~0.12），
    # 阈值定高会把正常问题挡掉。换成真正的 embedding 模型后可以往上调。
    knowledge_candidates: int = 20
    knowledge_top_k: int = 4
    knowledge_min_score: float = 0.05
    # 启动时自动建表并建索引（幂等；失败只告警，不影响服务启动）
    knowledge_auto_index: bool = True

    @field_validator("embedding_dim", mode="before")
    @classmethod
    def _blank_dim_means_auto(cls, value):
        """`EMBEDDING_DIM=` 这种留空写法要当成「自动探测」，而不是解析失败。"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')


settings = Settings()

if settings.jwt_secret_key == "customer-service-dev-secret-please-change":
    logging.getLogger("ws.config").warning(
        "JWT_SECRET_KEY 未配置，正在使用内置默认密钥；部署前请通过环境变量覆盖。")
