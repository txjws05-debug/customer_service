from langchain.chat_models import init_chat_model

from ws.config.config import settings

# 初始化 LLM。
#
# 两处必须显式设置，缺一个就等于没有失败态：
# - timeout：单次请求上限。不设的时候，供应商卡住会让请求无限挂起，
#   uvicorn 的 worker 被逐个占满，整站跟着不可用；
# - max_retries=0：ChatOpenAI 自带 2 次内部重试，会和外层重试相乘（3×3=9 次），
#   把「快速失败」变成「越等越久」。重试统一交给外层 with_retry 管。
llm = init_chat_model(
    model_provider="openai",
    model=settings.llm_model,
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    temperature=1.1,
    timeout=settings.llm_timeout_seconds,
    max_retries=0,
)

# 瞬时限流 / 网络抖动时指数退避重试；退避上限压到 1s，避免退避本身吃掉预算。
# 最终仍失败由调用方经 as_chat_service_error 转成友好提示。
llm = llm.with_retry(
    stop_after_attempt=settings.llm_max_attempts,
    wait_exponential_jitter=True,
    exponential_jitter_params={"initial": 0.5, "max": 1.0},
)
