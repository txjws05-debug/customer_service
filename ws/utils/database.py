from sqlalchemy.ext.asyncio import  AsyncEngine,async_sessionmaker,AsyncSession,create_async_engine
from ws.config.config import settings
from ws.repository.orm.base import Base
from ws.repository.orm import dialogue_state  # noqa: F401  确保模型已注册到 metadata
from ws.repository.orm import user  # noqa: F401  确保 users 表模型已注册

engine:AsyncEngine|None=None
session_factory:async_sessionmaker[AsyncSession]|None=None
def init_db_engine():
    global engine,session_factory
    engine=create_async_engine(settings.database_url)
    session_factory=async_sessionmaker(engine,expire_on_commit=False)

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db_engine():
    global engine,session_factory
    if engine is not  None:
        await engine.dispose()
    engine=None
    session_factory=None