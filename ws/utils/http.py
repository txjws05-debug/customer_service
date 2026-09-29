import asyncio

import httpx
from httpx import AsyncClient

from ws.utils.errors import ChatServiceError

http_client: AsyncClient | None = None


# 初始化方法
def init_http_client():
    global http_client
    http_client = AsyncClient(timeout=10.0)


async def close_http_client():
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None


async def get_api_data(url: str) -> object:
    """调用电商中台 GET 接口，返回响应体中的 data 字段。

    把网络错误、非 200、非法 JSON、缺少 data 等情况统一转成
    面向用户的 ChatServiceError，避免 KeyError / 状态码异常直接变成 500。
    """
    if http_client is None:
        raise ChatServiceError("系统正在启动中，请稍后再试。")

    try:
        response = await http_client.get(url)
    except httpx.HTTPError:
        raise ChatServiceError("网络繁忙，请稍后再试。")

    if response.status_code != 200:
        raise ChatServiceError(
            f"服务暂时不可用，请稍后再试（HTTP {response.status_code}）。")

    try:
        body = response.json()
    except ValueError:
        raise ChatServiceError("服务返回了无法解析的内容，请稍后再试。")

    if not isinstance(body, dict) or "data" not in body:
        raise ChatServiceError("没有查询到相关信息。")

    return body["data"]


# 测试
async def test():
    init_http_client()
    data = await get_api_data("http://127.0.0.1:18081/users/u1001/orders")
    print(data)
    await close_http_client()


if __name__ == "__main__":
    asyncio.run(test())
