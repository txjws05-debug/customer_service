from langchain.chat_models import init_chat_model

from ws.config.config import settings

# 初始化 LLM
llm = init_chat_model(
    model_provider="openai",
    model=settings.llm_model,
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    temperature=1.1,
)

# 瞬时限流 / 网络抖动时自动指数退避重试一次；
# 最终仍失败由调用方经 as_chat_service_error 转成友好提示。
llm = llm.with_retry(
    stop_after_attempt=2,
    wait_exponential_jitter=True,
)
