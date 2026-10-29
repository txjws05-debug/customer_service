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

    # 单次 LLM 请求的超时（秒）。没有这个上限，供应商抖动时请求会一直挂着，
    # 整个对话链路跟着一起瘫 —— 这是本项目最致命的一处「无失败态设计」。
    llm_timeout_seconds: float = 8.0
    # 最多尝试几次。8s × 2 次 + 退避 ≈ 16.5s，仍在 20s 总预算内；
    # 再叠加就会击穿接口 25s 上限，宁可快速失败给用户一句降级话术。
    llm_max_attempts: int = 2
    # 流式首包超时：超过这个时间还没吐出第一个字，就不让用户干等
    llm_first_token_timeout: float = 6.0

    # 数据库
    database_url: str

    # 商城 API
    commerce_api_base_url: str

    # 调中台时带的服务令牌（中台 AUTH_ENFORCE=on 时必填）。
    # 留空则不带该请求头 —— 本地开发/灰度期不受影响。
    commerce_service_token: str = ""

    # 登录用户 → 商城用户号的兜底映射（演示用）。
    # 真实系统应该是一张「账号绑定」表（用户在自己的个人中心绑定商城账号）；
    # 演示环境里，登录名不是商城号时统一按这个账号办理交易，
    # 这样「加购/下单/查券」都能直接演示。留空则不做兜底，提示用户去绑定。
    commerce_default_user_id: str = "u1001"

    # JWT：本地兜底默认值，推荐通过 .env / 环境变量覆盖
    jwt_secret_key: str = "customer-service-dev-secret-please-change"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # 服务器
    app_host: str
    app_port: int

    # 生产环境关闭 /docs、/redoc、/openapi.json：接口形状不该公网可见。
    # 关掉后健康检查改走 /health（见 docker-compose.prod.yml）。
    expose_docs: bool = True

    # /metrics 的访问令牌：为空则不限（本地开发）；设了就必须带 Bearer。
    # 指标会暴露路径、错误率、耗时分布，不该对公网裸奔。
    metrics_token: str = ""

    # 对话限流：单用户每分钟最多几条。防脚本刷，也防手滑连点。
    chat_rate_limit_per_minute: int = 30
    # 全站每日 token 预算（0=不限）。模型按 token 计费，跑飞了只能靠它拦。
    chat_daily_token_budget: int = 300000

    # 运营接口（人工工单队列）的访问令牌；为空则该组接口直接 403
    operator_token: str = ""

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
    # 字面分口径：similarity（trigram 交集/并集）| word_similarity（查询侧覆盖率）
    # | none（纯向量）。默认 word_similarity 是评测结论：在 41 条评测集上
    # Recall@1 97.2% → 100%、MRR 0.986 → 1.000（短问长答场景下 similarity 会被
    # 长文档的 trigram 稀释）。复现：python -m ws.knowledge.eval --backend db --sweep
    knowledge_keyword_mode: str = "word_similarity"
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
