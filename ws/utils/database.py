from sqlalchemy.ext.asyncio import  AsyncEngine,async_sessionmaker,AsyncSession,create_async_engine
from ws.config.config import settings

engine:AsyncEngine|None=None
session_factory:async_sessionmaker[AsyncSession]|None=None
def init_db_engine():
    global engine,session_factory
    engine=create_async_engine(settings.database_url)
    session_factory=async_sessionmaker(engine,expire_on_commit=False)
async def close_db_engine():
    global engine,session_factory
    if engine is not  None:
        await engine.dispose()
    engine=None
    session_factory=None
async def close_engine():
    await engine.dispose()