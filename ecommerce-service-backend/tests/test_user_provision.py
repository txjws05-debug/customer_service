"""开户：客服端注册新账号时，由中台分配一个全新的商城账号。

此前客服端靠「用户名长得像 u1001 就当商城号、否则回落 u1001」做映射：
注册一个叫 u1002 的账号就能冒领别人的订单与地址，其余所有账号共用 u1001。
改成由中台分配之后，商城号只能由服务端生成，用户无从指定。
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app import models


def _provision(client, headers, nickname="alice"):
    return client.post("/shop/users", json={"nickname": nickname}, headers=headers)


def test_service_token_provisions_a_fresh_account(client, db, enforced_service_token):
    existing = set(db.scalars(select(models.User.user_id)))
    first = _provision(client, {"X-Service-Token": enforced_service_token})
    second = _provision(client, {"X-Service-Token": enforced_service_token}, "bob")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    a, b = first.json()["data"]["user_id"], second.json()["data"]["user_id"]
    assert re.fullmatch(r"u\d+", a) and re.fullmatch(r"u\d+", b)
    assert a != b and a not in existing and b not in existing

    db.expire_all()
    user = db.scalar(select(models.User).filter(models.User.user_id == a))
    assert user is not None and user.nickname == "alice"
    assert not user.orders and not user.addresses


def test_agent_acting_for_a_user_cannot_provision(client, enforced_service_token):
    resp = _provision(client, {"X-Service-Token": enforced_service_token,
                               "X-On-Behalf-Of": "u1001"})
    assert resp.status_code == 403, resp.text


def test_anonymous_cannot_provision(client, enforced_service_token):
    assert _provision(client, {}).status_code == 401
