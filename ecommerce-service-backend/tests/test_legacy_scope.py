"""老接口 /orders/* 的对象级授权回归测试。

为什么单独一份：test_security.py 断言的是 ensure_order_scope 函数本身
（传 FakeOrder），函数全绿并不说明每个 HTTP 端点都接上了校验。
2026-11 就漏过一处——/orders/* 下五个端点没有调用它，任意登录用户
可以读到他人的收货人姓名、电话与地址。这份测试直接打端点。

新增订单相关端点时，请在这里补一条断言：函数级测试兜不住接入缺口。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from app import models
from app.config import settings


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(sub: str, cuid: str | None) -> str:
    """按 app.security.decode_jwt 的口径签一个 HS256 token（不引第三方库）。"""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = {"sub": sub, "exp": int(time.time()) + 3600}
    if cuid:
        payload["cuid"] = cuid
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.jwt_secret.encode(), f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"




def _an_order_of(db, user_id: str) -> str:
    order_id = db.scalar(
        select(models.Order.order_id)
        .join(models.User, models.User.id == models.Order.user_id)
        .where(models.User.user_id == user_id)
        .order_by(models.Order.order_id)
    )
    assert order_id, f"种子数据缺少 {user_id} 的订单"
    return order_id


@pytest.mark.parametrize("suffix", ["", "/status", "/logistics"])
def test_other_users_order_is_404(client, db, suffix):
    """u1001 读 u1002 的订单：三个读端点都必须是 404。"""
    other = _an_order_of(db, "u1002")
    resp = client.get(
        f"/orders/{other}{suffix}",
        headers={"Authorization": f"Bearer {_token('u1001', 'u1001')}"},
    )
    assert resp.status_code == 404, resp.text


def test_own_order_is_200(client, db):
    mine = _an_order_of(db, "u1001")
    resp = client.get(
        f"/orders/{mine}",
        headers={"Authorization": f"Bearer {_token('u1001', 'u1001')}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["order_id"] == mine


def test_service_token_still_crosses_users(client, db):
    """客服 Agent 持服务令牌代调用，不能被误伤。"""
    other = _an_order_of(db, "u1002")
    resp = client.get(
        f"/orders/{other}",
        headers={"X-Service-Token": settings.service_token},
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def enforced_service_token(monkeypatch):
    """测试环境默认没配服务令牌、AUTH_ENFORCE=off，那样请求会被当成匿名放行，
    断言就测不出东西。这里显式打开。"""
    import dataclasses

    from app import security

    patched = dataclasses.replace(security.settings, service_token="svc-test",
                                  auth_enforce="on")
    monkeypatch.setattr(security, "settings", patched)
    return "svc-test"


def test_agent_on_behalf_cannot_read_others_order(client, db, enforced_service_token):
    """对话里报别人的订单号：Agent 代 u1001 调用，必须 404。"""
    other = _an_order_of(db, "u1002")
    for suffix in ("", "/status", "/logistics"):
        resp = client.get(f"/orders/{other}{suffix}", headers={
            "X-Service-Token": enforced_service_token, "X-On-Behalf-Of": "u1001"})
        assert resp.status_code == 404, (suffix, resp.text)
    resp = client.get(f"/shop/orders/{other}", headers={
        "X-Service-Token": enforced_service_token, "X-On-Behalf-Of": "u1001"})
    assert resp.status_code == 404, resp.text


def test_agent_on_behalf_reads_own_order(client, db, enforced_service_token):
    mine = _an_order_of(db, "u1001")
    resp = client.get(f"/orders/{mine}/status", headers={
        "X-Service-Token": enforced_service_token, "X-On-Behalf-Of": "u1001"})
    assert resp.status_code == 200, resp.text


def test_agent_on_behalf_cannot_reach_admin(client, enforced_service_token):
    """订单号里塞 ../ 被规范化到 /shop/admin 时，代用户身份也进不去运营端。"""
    resp = client.get("/shop/admin/orders", headers={
        "X-Service-Token": enforced_service_token, "X-On-Behalf-Of": "u1001"})
    assert resp.status_code == 403, resp.text
