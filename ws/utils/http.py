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


async def _request_api(method: str, url: str, json_body: dict | None = None) -> object:
    """调用电商中台，返回响应体中的 data 字段。

    把网络错误、非 200、非法 JSON、缺少 data 等情况统一转成面向用户的
    ChatServiceError，避免 KeyError / 状态码异常直接变成 500。

    交易域（/shop/*）的业务失败也走统一信封 {code, message, data}：
    这类 message 本来就是写给用户看的（「库存不足」「优惠券未满足门槛」），
    必须原样透传；否则用户只会看到一句「服务暂时不可用」，完全不知道哪里错了。
    """
    if http_client is None:
        raise ChatServiceError("系统正在启动中，请稍后再试。")

    try:
        response = await http_client.request(method, url, json=json_body)
    except httpx.HTTPError:
        raise ChatServiceError("网络繁忙，请稍后再试。")

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 200:
        if not isinstance(body, dict) or "data" not in body:
            raise ChatServiceError("没有查询到相关信息。")
        return body["data"]

    if isinstance(body, dict):
        # 交易域是 message，老接口是 FastAPI 的 detail，两种都要透传
        for key in ("message", "detail"):
            message = body.get(key)
            if message:
                raise ChatServiceError(str(message))

    raise ChatServiceError(
        f"服务暂时不可用，请稍后再试（HTTP {response.status_code}）。")


async def get_api_data(url: str) -> object:
    """调用电商中台 GET 接口，返回 data 字段。"""
    return await _request_api("GET", url)


async def post_api_data(url: str, json_body: dict | None = None) -> object:
    """调用电商中台 POST 接口（加购、下单、支付、收货、售后等）。"""
    return await _request_api("POST", url, json_body)


async def patch_api_data(url: str, json_body: dict | None = None) -> object:
    """调用电商中台 PATCH 接口（修改购物车数量/勾选状态等）。"""
    return await _request_api("PATCH", url, json_body)


async def delete_api_data(url: str) -> object:
    """调用电商中台 DELETE 接口（删除购物车条目）。"""
    return await _request_api("DELETE", url)


# 测试
async def test():
    init_http_client()
    data = await get_api_data("http://127.0.0.1:18081/users/u1001/orders")
    print(data)
    await close_http_client()


if __name__ == "__main__":
    asyncio.run(test())
