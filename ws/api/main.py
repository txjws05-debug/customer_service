import asyncio

import uvicorn

from ws.config.config import settings
from ws.utils.database import init_db_engine, create_tables
from ws.utils.http import init_http_client


async def main():
    init_db_engine()
    await create_tables()
    init_http_client()
    config = uvicorn.Config(
        "ws.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
