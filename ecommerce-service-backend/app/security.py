"""中台统一接入鉴权。

三种凭证，各管一段：

- 服务令牌 `X-Service-Token`：客服 Agent 调中台时用，可跨用户操作；
- 用户 JWT `Authorization: Bearer`：浏览器直连中台时用，只能碰自己的数据；
- 运营令牌 `X-Operator-Token`：商家后台用，只保护 `/shop/admin/*`。

三档开关 `AUTH_ENFORCE`：

- `off`（默认）：一律放行，行为与改造前完全一致，用于灰度；
- `warn`：校验失败只记日志并按匿名放行，观察期用；
- `on`：校验失败返回 401/403。

为什么不用 pyjwt：这台机器访问不了 PyPI，镜像重建也吃紧，所以用标准库实现
HS256 校验（`alg` 只接受 HS256，签名用 `compare_digest` 定时比较）。
算法固定、不接受 "none"、过期留 60s 时钟偏移余量，安全性等价。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

# 匿名也允许的路径：健康检查 + 商品只读（首页与商品详情不登录也能看）
_PUBLIC_EXACT = {"/", "/health", "/openapi.json", "/docs", "/redoc"}
_PUBLIC_PREFIXES = ("/docs", "/redoc")
_PUBLIC_READ = {"/shop/products", "/shop/categories"}

_JWT_LEEWAY = 60


@dataclass(frozen=True)
class AuthContext:
    """一次请求的身份。kind 只有四种取值。"""

    kind: str                      # service | operator | user | anonymous
    subject: str = ""              # 服务名 / 运营 / 登录名
    cuid: str | None = None        # 商城账号（u1001 这种），仅 user 有

    @property
    def is_privileged(self) -> bool:
        """服务与运营可以跨用户操作；普通用户只能碰自己的。"""
        return self.kind in ("service", "operator")


ANONYMOUS = AuthContext(kind="anonymous")
_current: ContextVar[AuthContext] = ContextVar("auth_context", default=ANONYMOUS)


def current_context() -> AuthContext:
    """取当前请求的身份。没经过中间件（如单测直调服务层）时是 anonymous。"""
    return _current.get()


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _safe_equals(left: str | None, right: str | None) -> bool:
    """定时安全比较，且对 None / 非 ASCII 输入不抛异常。"""
    if not left or not right:
        return False
    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def decode_jwt(token: str, secret: str) -> dict | None:
    """校验并解出 payload；任何不合规都返回 None（不抛异常给调用方）。"""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            logger.warning("JWT 拒绝：alg 不是 HS256（%r）", header.get("alg") if isinstance(header, dict) else header)
            return None
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{header_b64}.{payload_b64}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and time.time() > exp + _JWT_LEEWAY:
        return None
    return payload


def resolve(request: Request) -> AuthContext:
    """按「服务令牌 → 运营令牌 → 用户 JWT」的顺序识别身份。"""
    if _safe_equals(request.headers.get("x-service-token"), settings.service_token):
        return AuthContext(kind="service", subject="customer-service-agent")

    if _safe_equals(request.headers.get("x-operator-token"), settings.operator_token):
        return AuthContext(kind="operator", subject="operator")

    authorization = request.headers.get("authorization") or ""
    if authorization[:7].lower() == "bearer ":
        payload = decode_jwt(authorization[7:].strip(), settings.jwt_secret)
        if payload:
            subject = str(payload.get("sub") or "")
            cuid = payload.get("cuid")
            return AuthContext(
                kind="user",
                subject=subject,
                cuid=str(cuid) if cuid else None,
            )
    return ANONYMOUS


def _deny(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"code": status, "message": message, "data": None})


class AuthMiddleware(BaseHTTPMiddleware):
    """解析身份 → 写入 ContextVar → 按模式决定拦不拦。

    挂中间件而不是逐个路由加依赖，是因为对象级授权要在服务层（`get_user` /
    `_get_order`）统一生效；那样既覆盖现有全部接口，也不会漏掉以后新加的。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)
        if request.method == "GET" and path in _PUBLIC_READ:
            return await call_next(request)

        ctx = resolve(request)
        reset = _current.set(ctx)
        try:
            mode = settings.auth_enforce
            if ctx.kind == "anonymous":
                if mode == "on":
                    return _deny(401, "缺少或无效的访问凭证")
                if mode == "warn":
                    logger.warning("AUTH_WARN 匿名放行 %s %s", request.method, path)
            # 运营端同样只在 on 模式下才拦：off/warn 必须保持改造前的行为，
            # 否则灰度期一上线就把商家后台和既有测试全打成 403。
            if settings.auth_enforce == "on" and path.startswith("/shop/admin") \
                    and not ctx.is_privileged:
                logger.warning("AUTH 运营端越权 path=%s kind=%s", path, ctx.kind)
                return _deny(403, "需要运营权限")
            return await call_next(request)
        finally:
            _current.reset(reset)
