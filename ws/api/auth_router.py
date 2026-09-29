from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ws.api.deps import get_session
from ws.api.schemas import AuthRequest, TokenResponse
from ws.repository.user_repository import UserRepository
from ws.security.jwt import create_access_token
from ws.security.password import hash_password, verify_password

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _build_token_response(username: str) -> TokenResponse:
    token = create_access_token(username)
    return TokenResponse(access_token=token, username=username)


@auth_router.post("/register")
async def register(body: AuthRequest,
                   session: AsyncSession = Depends(get_session)
                   ) -> TokenResponse:
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    repo = UserRepository(session)
    if await repo.get_by_username(username):
        raise HTTPException(status_code=400, detail="该用户名已被注册")

    await repo.create(username, hash_password(body.password))
    await session.commit()
    return _build_token_response(username)


@auth_router.post("/login")
async def login(body: AuthRequest,
                session: AsyncSession = Depends(get_session)
                ) -> TokenResponse:
    username = body.username.strip()
    repo = UserRepository(session)
    user = await repo.get_by_username(username)

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return _build_token_response(username)
