from datetime import datetime, timedelta, timezone

import jwt

from ws.config.config import settings

def create_access_token(username: str, cuid: str | None) -> str:
    """以 username 为 subject 签发 JWT，并带上已绑定的商城账号号（cuid）。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "exp": expire}
    if cuid:
        # 中台靠它做对象级授权；缺了就会被拒（宁可重登，也不能回落成默认账号）
        payload["cuid"] = cuid
    return jwt.encode(payload, settings.jwt_secret_key,
                      algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """校验并解码 JWT，返回其中的 username（subject）。"""
    payload = jwt.decode(token, settings.jwt_secret_key,
                         algorithms=[settings.jwt_algorithm])
    return payload["sub"]
