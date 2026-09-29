from datetime import datetime, timedelta, timezone

import jwt

from ws.config.config import settings


def create_access_token(username: str) -> str:
    """以 username 为 subject 签发 JWT。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key,
                      algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """校验并解码 JWT，返回其中的 username（subject）。"""
    payload = jwt.decode(token, settings.jwt_secret_key,
                         algorithms=[settings.jwt_algorithm])
    return payload["sub"]
