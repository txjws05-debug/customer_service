import asyncio
from httpx import  AsyncClient
from openai import http_client | None=None

#初始化方法
def init_http_client():
    global http_client
    http_client=AsyncClient(timeout=10.0)

async def close_http_client():
    await http_client.aclose()

#测试
async def test():
    init_http_client()
    response=await http_client.get(
        url="http:1127.0.0.1:18081/users/u1001/orders")
    print(response.json())

if __name__=="__main__":
    asyncio.run(test())