from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ws.api.deps import get_session
from ws.api.schemas import AuthRequest, TokenResponse
from ws.repository.commerce_account_repository import CommerceAccountRepository
from ws.repository.user_repository import UserRepository
from ws.security.jwt import create_access_token
from ws.security.password import hash_password, verify_password
from ws.service.account_service import AccountError, AccountService
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import provision_commerce_account

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _accounts(session: AsyncSession) -> AccountService:
    return AccountService(UserRepository(session),
                          CommerceAccountRepository(session),
                          provision_commerce_account)


def _build_token_response(username: str, cuid: str) -> TokenResponse:
    token = create_access_token(username, cuid)
    return TokenResponse(access_token=token, username=username,
                         commerce_user_id=cuid)


@auth_router.post("/register")
async def register(body: AuthRequest,
                   session: AsyncSession = Depends(get_session)
                   ) -> TokenResponse:
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    try:
        cuid = await _accounts(session).register(username, hash_password(body.password))
    except AccountError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except ChatServiceError:
        # 开户失败：客服账号也不留，否则会出现「能登录、却没有商城号」的半成品
        await session.rollback()
        raise HTTPException(status_code=503, detail="注册暂时不可用，请稍后再试")
    await session.commit()
    return _build_token_response(username, cuid)


@auth_router.post("/login")
async def login(body: AuthRequest,
                session: AsyncSession = Depends(get_session)
                ) -> TokenResponse:
    username = body.username.strip()
    user = await UserRepository(session).get_by_username(username)

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    try:
        cuid = await _accounts(session).ensure_account(username)
    except ChatServiceError:
        await session.rollback()
        raise HTTPException(status_code=503, detail="登录暂时不可用，请稍后再试")
    await session.commit()
    return _build_token_response(username, cuid)
