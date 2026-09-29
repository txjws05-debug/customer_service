import asyncio

import uvicorn

from ws.config.config import settings


async def main():
    # 数据库、HTTP 客户端、引擎单例均由 app 的 lifespan 统一初始化与关闭
    config = uvicorn.Config(
        "ws.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
