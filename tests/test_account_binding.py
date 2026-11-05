"""客服账号 → 商城账号：由服务端开户并绑定，用户无从指定。

此前的规则是「用户名长得像 u1001 就当商城号，否则回落 u1001」：
注册一个叫 u1002 的账号就能冒领别人的订单与收货地址，其余所有账号共用 u1001。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import jwt as pyjwt
import pytest

from ws.config.config import settings
from ws.service.account_service import AccountError, AccountService
from ws.security.jwt import create_access_token
from ws.utils import http as http_module
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import current_commerce_user, provision_commerce_account


class _Users:
    def __init__(self):
        self.rows: dict[str, str] = {}

    async def get_by_username(self, username):
        return username if username in self.rows else None

    async def create(self, username, password_hash):
        self.rows[username] = password_hash


class _Accounts:
    def __init__(self, **existing):
        self.rows: dict[str, str] = dict(existing)

    async def get_cuid(self, username):
        return self.rows.get(username)

    async def bind(self, username, cuid):
        self.rows[username] = cuid


class _Provisioner:
    def __init__(self, start=1007, fail=False):
        self.next, self.fail, self.calls = start, fail, []

    async def __call__(self, nickname):
        self.calls.append(nickname)
        if self.fail:
            raise ChatServiceError("服务暂时不可用")
        self.next += 1
        return f"u{self.next - 1}"


def _service(accounts=None, provisioner=None):
    users, accounts = _Users(), accounts or _Accounts()
    provisioner = provisioner or _Provisioner()
    return AccountService(users, accounts, provisioner), users, accounts, provisioner


def test_register_provisions_a_fresh_account_and_binds_it():
    svc, users, accounts, prov = _service()
    cuid = asyncio.run(svc.register("alice", "hash"))
    assert cuid == "u1007"
    assert accounts.rows == {"alice": "u1007"}
    assert "alice" in users.rows and prov.calls == ["alice"]


def test_username_that_looks_like_a_shop_id_cannot_claim_it():
    """冒领漏洞本身：注册名叫 u1002，拿到的也必须是新开的号。"""
    svc, *_ = _service()
    assert asyncio.run(svc.register("u1002", "hash")) == "u1007"


def test_duplicate_username_is_rejected():
    svc, *_ = _service()
    asyncio.run(svc.register("alice", "hash"))
    with pytest.raises(AccountError):
        asyncio.run(svc.register("alice", "hash"))


def test_register_fails_when_provisioning_fails():
    svc, users, accounts, _ = _service(provisioner=_Provisioner(fail=True))
    with pytest.raises(ChatServiceError):
        asyncio.run(svc.register("alice", "hash"))
    assert accounts.rows == {}


def test_legacy_account_gets_its_own_account_once():
    """改造前注册的账号没有绑定：首次登录开一个新号，以后复用，不再回落 u1001。"""
    svc, _, accounts, prov = _service()
    first = asyncio.run(svc.ensure_account("demo_shot01"))
    again = asyncio.run(svc.ensure_account("demo_shot01"))
    assert first == again == "u1007" and len(prov.calls) == 1


def test_existing_binding_is_reused():
    svc, _, _, prov = _service(accounts=_Accounts(u1001="u1001"))
    assert asyncio.run(svc.ensure_account("u1001")) == "u1001"
    assert prov.calls == []


def test_token_carries_the_bound_account():
    token = create_access_token("alice", "u1007")
    payload = pyjwt.decode(token, settings.jwt_secret_key,
                           algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "alice" and payload["cuid"] == "u1007"


# ------------------------------------------------------------ 动作侧取号
def test_actions_use_the_bound_account_not_the_username():
    token = http_module.bind_on_behalf("u1007")
    try:
        assert current_commerce_user() == "u1007"
    finally:
        http_module.reset_on_behalf(token)


@pytest.mark.parametrize("bound", ["", None])
def test_actions_refuse_without_a_bound_account(bound):
    token = http_module._on_behalf.set(bound)
    try:
        with pytest.raises(ChatServiceError):
            current_commerce_user()
    finally:
        http_module._on_behalf.reset(token)


# ------------------------------------------------------------ 开户调用
def test_provisioning_calls_shop_without_acting_for_anyone(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "message": "ok",
                                         "data": {"user_id": "u1009", "nickname": "alice"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(http_module, "http_client", client)
    try:
        assert asyncio.run(provision_commerce_account("alice")) == "u1009"
    finally:
        asyncio.run(client.aclose())
    assert seen[0].method == "POST" and seen[0].url.path == "/shop/users"
    assert json.loads(seen[0].content) == {"nickname": "alice"}
    assert "x-on-behalf-of" not in seen[0].headers
