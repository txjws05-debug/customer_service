from fastapi import HTTPException, Request
from fastapi.params import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from ws.engine.dialogue_engine import DialogueEngine
from ws.repository.dialogue_repository import DialogueRepository
from ws.security.jwt import decode_access_token
from ws.service.dialogue_service import DialogueService
from ws.utils import database

# JWT Bearer 安全方案
_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    """校验 Authorization: Bearer <token>，返回 username；失败返回 401。"""
    try:
        return decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401,
                            detail="登录凭证无效或已过期，请重新登录")


async def get_session():
    async with database.session_factory() as session:
        yield session


async def get_dialogue_engine(request: Request) -> DialogueEngine:
    """引擎在 lifespan 中构建一次，所有请求共享同一个实例。"""
    return request.app.state.dialogue_engine


async def get_dialogue_repository(session: AsyncSession = Depends(get_session)):
    return DialogueRepository(session=session)


async def get_dialogue_service(
        dialogue_repository: DialogueRepository = Depends(get_dialogue_repository),
        dialogue_engine: DialogueEngine = Depends(get_dialogue_engine)):
    return DialogueService(
        dialogue_repository=dialogue_repository,
        dialogue_engine=dialogue_engine)
