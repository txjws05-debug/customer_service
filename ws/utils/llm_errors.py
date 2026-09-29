from ws.utils.errors import ChatServiceError


def as_chat_service_error(exc: Exception) -> ChatServiceError:
    """把各类 LLM / 网络异常映射成用户能理解的一句提示。

    仅做归类与文案转换，不吞异常、不改变调用流程。
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if "rate limit" in msg or "429" in msg or "rate_limit" in name or "quota" in msg:
        return ChatServiceError("当前咨询量较大，请稍后再试。")

    if "timeout" in name or "timed out" in msg or "timeout" in msg:
        return ChatServiceError("响应超时，请稍后再试。")

    if "connection" in msg or "unreachable" in msg or "connect" in name:
        return ChatServiceError("网络连接异常，请稍后再试。")

    if "authentication" in msg or "api key" in msg or "401" in msg or "invalid api" in msg:
        return ChatServiceError("客服认证配置异常，请联系管理员。")

    return ChatServiceError("客服暂时出了点问题，请稍后再试。")
