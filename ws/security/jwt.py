import re
from datetime import datetime, timedelta, timezone

import jwt

from ws.config.config import settings

_SHOP_ACCOUNT = re.compile(r"^u\d+$")


def resolve_cuid(username: str) -> str | None:
    """登录名 → 商城账号号。

    登录名本身就是商城号（u1001）就直接用，否则按演示配置回落到默认账号。
    这条规则必须与前端 `currentShopUser()` 保持一致 —— 中台拿它做对象级授权，
    两边算出来的号不一致，用户就会看不到自己的订单。
    """
    if _SHOP_ACCOUNT.match(username or ""):
        return username
    return settings.commerce_default_user_id or None


def create_access_token(username: str) -> str:
    """以 username 为 subject 签发 JWT，并带上商城账号号（cuid）。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "exp": expire}
    cuid = resolve_cuid(username)
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
