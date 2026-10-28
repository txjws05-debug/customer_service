"""鉴权与对象级授权的单元测试。

这一层是「安全边界」，必须能被本地断言覆盖：
- JWT 校验拒绝伪造签名、拒绝 alg=none、拒绝过期；
- 三种凭证的识别顺序正确；
- 普通用户碰别人的购物车/订单会被拦，服务令牌与运营令牌可以跨用户。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import security
from app.security import AuthContext, decode_jwt, resolve
from app.shop_service import ShopError

SECRET = "test-secret-for-unit-tests"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def stub_settings(monkeypatch, **overrides):
    """settings 是 frozen dataclass，不能直接 setattr；替换模块级引用即可。"""
    defaults = {
        "service_token": "",
        "operator_token": "",
        "jwt_secret": "",
        "auth_enforce": "off",
        "expose_docs": True,
    }
    defaults.update(overrides)
    monkeypatch.setattr(security, "settings", SimpleNamespace(**defaults))


def make_jwt(payload: dict, *, secret: str = SECRET, alg: str = "HS256") -> str:
    header = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    if alg == "none":
        return f"{header}.{body}."
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def make_request(**headers: str) -> Request:
    raw = [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/shop/products", "headers": raw})


# ------------------------------------------------------------------ JWT
def test_jwt_accepts_valid_token():
    token = make_jwt({"sub": "22", "cuid": "u1001", "exp": time.time() + 60})
    payload = decode_jwt(token, SECRET)
    assert payload is not None
    assert payload["cuid"] == "u1001"


def test_jwt_rejects_wrong_signature():
    token = make_jwt({"sub": "22"}, secret="another-secret")
    assert decode_jwt(token, SECRET) is None


def test_jwt_rejects_alg_none():
    token = make_jwt({"sub": "22"}, alg="none")
    assert decode_jwt(token, SECRET) is None


def test_jwt_rejects_expired_beyond_leeway():
    token = make_jwt({"sub": "22", "exp": time.time() - 3600})
    assert decode_jwt(token, SECRET) is None


def test_jwt_tolerates_small_clock_drift():
    token = make_jwt({"sub": "22", "exp": time.time() - 5})
    assert decode_jwt(token, SECRET) is not None


def test_jwt_rejects_garbage():
    assert decode_jwt("not-a-jwt", SECRET) is None
    assert decode_jwt("a.b", SECRET) is None


# ---------------------------------------------------------------- 凭证识别
def test_resolve_prefers_service_token(monkeypatch):
    stub_settings(monkeypatch, service_token="svc-123")
    request = make_request(x_service_token="svc-123")
    ctx = resolve(request)
    assert ctx.kind == "service"


def test_resolve_service_token_must_match_exactly(monkeypatch):
    stub_settings(monkeypatch, service_token="svc-123")
    request = make_request(x_service_token="svc-1234")
    assert resolve(request).kind == "anonymous"


def test_resolve_operator_token(monkeypatch):
    stub_settings(monkeypatch, operator_token="ops-9")
    assert resolve(make_request(x_operator_token="ops-9")).kind == "operator"


def test_resolve_bearer_without_cuid(monkeypatch):
    stub_settings(monkeypatch, jwt_secret=SECRET)
    token = make_jwt({"sub": "22", "exp": time.time() + 60})
    ctx = resolve(make_request(authorization=f"Bearer {token}"))
    assert ctx.kind == "user"
    # 旧 token 没有 cuid：必须保持 None，绝不能回落成默认账号
    assert ctx.cuid is None


def test_resolve_bearer_reads_cuid(monkeypatch):
    stub_settings(monkeypatch, jwt_secret=SECRET)
    token = make_jwt({"sub": "22", "cuid": "u1002", "exp": time.time() + 60})
    assert resolve(make_request(authorization=f"Bearer {token}")).cuid == "u1002"


def test_resolve_anonymous_when_nothing_sent():
    assert resolve(make_request()).kind == "anonymous"


# ------------------------------------------------------------ 对象级授权
class FakeUser:
    def __init__(self, user_id: str):
        self.user_id = user_id


class FakeOrder:
    def __init__(self, order_id: str, owner: str | None):
        self.order_id = order_id
        self.user = FakeUser(owner) if owner else None


@pytest.fixture
def as_user():
    def _apply(cuid: str | None, kind: str = "user"):
        token = security._current.set(AuthContext(kind=kind, subject="22", cuid=cuid))
        return token

    return _apply


def test_user_can_access_own_cart(as_user):
    from app.ownership import ensure_user_scope

    as_user("u1001")
    ensure_user_scope("u1001")  # 不抛异常即通过


def test_user_cannot_access_other_cart(as_user):
    from app.ownership import ensure_user_scope

    as_user("u1001")
    with pytest.raises(ShopError) as exc:
        ensure_user_scope("u1002")
    assert exc.value.status_code == 403


def test_legacy_token_without_cuid_is_rejected(as_user):
    from app.ownership import ensure_user_scope

    as_user(None)
    with pytest.raises(ShopError) as exc:
        ensure_user_scope("u1001")
    assert exc.value.status_code == 403


def test_service_token_crosses_users(as_user):
    from app.ownership import ensure_order_scope, ensure_user_scope

    as_user(None, kind="service")
    ensure_user_scope("u1002")
    ensure_order_scope(FakeOrder("SO1", "u1002"))


def test_user_cannot_read_other_order(as_user):
    from app.ownership import ensure_order_scope

    as_user("u1001")
    with pytest.raises(ShopError) as exc:
        ensure_order_scope(FakeOrder("SO1", "u1002"))
    # 别人的订单必须是 404：403 等于承认订单号存在，会成为枚举通道
    assert exc.value.status_code == 404


def test_user_can_read_own_order(as_user):
    from app.ownership import ensure_order_scope

    as_user("u1001")
    ensure_order_scope(FakeOrder("SO1", "u1001"))


def test_anonymous_keeps_legacy_behaviour(as_user):
    from app.ownership import ensure_user_scope

    as_user(None, kind="anonymous")
    ensure_user_scope("u1002")  # AUTH_ENFORCE=off 期间的既有行为
