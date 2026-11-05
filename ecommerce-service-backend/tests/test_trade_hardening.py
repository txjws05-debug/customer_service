"""交易链路加固（独立审查发现的 P1 缺陷）。每条用例在修复前都能红。

- 售后单不校验归属：拿到工单号的任何登录用户都能查看/撤销别人的售后；
- 售后可重复退全款：只拦「进行中」的单，完成一单后还能再申请全额；
- 立即购买时同一 SKU 出现两行：逐行校验库存、累加扣减，库存被扣成负数；
- 订单状态变更不锁订单行：并发取消会把库存/退款各做多遍；
- 优惠券不加锁：并发下单同一张券，多单同时拿到优惠；
- 幂等键全局共享：B 带上 A 用过的键，会被回放出 A 的订单。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import after_sale_service as after_sale
from app import models
from app.config import settings


def data_of(response) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwt(cuid: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": cuid, "cuid": cuid, "exp": int(time.time()) + 3600}).encode())
    sig = hmac.new(settings.jwt_secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def _set_stock(db, sku_code: str, stock: int) -> None:
    db.execute(text("UPDATE product_skus SET stock=:s WHERE sku_code=:c"),
               {"s": stock, "c": sku_code})
    db.commit()


def _stock(db, sku_code: str) -> int:
    db.expire_all()
    return db.scalar(select(models.ProductSku.stock)
                     .filter(models.ProductSku.sku_code == sku_code))


def _buy(client, user_id: str, sku_code: str, quantity: int = 1, pay: bool = True,
         headers: dict | None = None) -> dict:
    created = data_of(client.post("/shop/orders", headers=headers or {}, json={
        "user_id": user_id, "items": [{"sku_code": sku_code, "quantity": quantity}]}))
    if pay:
        data_of(client.post(f"/shop/orders/{created['order_id']}/pay",
                            json={"channel": "wechat"}, headers=headers or {}))
    return created


# ------------------------------------------------------------------ 售后归属
def test_other_user_cannot_see_or_cancel_my_after_sale(client, db, enforced_service_token):
    mine = {"Authorization": f"Bearer {_jwt('u1001')}"}
    theirs = {"Authorization": f"Bearer {_jwt('u1002')}"}
    _set_stock(db, "SKU10003-01", 50)
    created = _buy(client, "u1001", "SKU10003-01", headers=mine)
    ticket = data_of(client.post(f"/shop/orders/{created['order_id']}/after-sales",
                                 headers=mine, json={"user_id": "u1001",
                                                     "type": "refund_only", "reason": "不想要了"}))
    no = ticket["ticket_no"]
    assert client.get(f"/shop/after-sales/{no}", headers=theirs).status_code == 404
    assert client.post(f"/shop/after-sales/{no}/cancel", headers=theirs).status_code == 404
    assert client.get(f"/shop/after-sales/{no}", headers=mine).status_code == 200


# ------------------------------------------------------------------ 售后累计退款
def test_after_sale_cannot_refund_more_than_what_is_left(client, db):
    _set_stock(db, "SKU10003-01", 50)
    created = _buy(client, "u1001", "SKU10003-01", 2)
    order_id, payable = created["order_id"], Decimal(created["pay_amount"])

    first = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "少发一件", "refund_amount": "10.00"}))
    after_sale.review_ticket(db, first["ticket_no"], approved=True)
    after_sale.complete_after_sale(db, first["ticket_no"])

    # 已退 10 元，再申请全额必须被拒；申请剩余部分可以
    again = client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "再退一次",
        "refund_amount": str(payable)})
    assert again.status_code in (400, 409), again.text
    rest = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "退剩下的",
        "refund_amount": str(payable - Decimal("10.00"))}))
    assert Decimal(rest["refund_amount"]) == payable - Decimal("10.00")


# ------------------------------------------------------------------ 重复 SKU 行
def test_duplicate_sku_lines_cannot_oversell(client, db):
    sku = "SKU10006-01"
    _set_stock(db, sku, 3)
    resp = client.post("/shop/orders", json={"user_id": "u1001", "items": [
        {"sku_code": sku, "quantity": 2}, {"sku_code": sku, "quantity": 2}]})
    assert resp.status_code == 409, resp.text
    assert _stock(db, sku) == 3


def test_stock_can_never_go_negative(db):
    """库表兜底：即使上层校验漏了，库存也写不成负数。"""
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE product_skus SET stock=-1 WHERE sku_code='SKU10006-01'"))
        db.commit()
    db.rollback()


# ------------------------------------------------------------------ 订单行锁
def test_concurrent_cancels_restore_stock_once(client, db, monkeypatch):
    """两次取消同时进来：没有订单行锁时，两边都读到「待发货」，库存与退款各做两遍。"""
    from app import shop_service

    sku = "SKU10003-01"
    _set_stock(db, sku, 50)
    # 未付款订单：已付款的会被退款上限兜住（第二次退款超实付 → 整单回滚），
    # 未付款的没有这道兜底，库存会被归还两次
    created = _buy(client, "u1001", sku, 1, pay=False)
    before = _stock(db, sku)

    original = shop_service._change_stock

    def slow_change_stock(*args, **kwargs):
        time.sleep(0.4)  # 卡在「已读状态、未提交」之间，让另一次取消必然撞上
        return original(*args, **kwargs)

    monkeypatch.setattr(shop_service, "_change_stock", slow_change_stock)
    gate = threading.Barrier(2)

    def cancel():
        gate.wait()
        return client.post(f"/shop/orders/{created['order_id']}/cancel",
                           json={"reason": "并发取消"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = [f.result() for f in [pool.submit(cancel) for _ in range(2)]]

    assert sorted(codes) == [200, 409], codes
    assert _stock(db, sku) == before + 1


# ------------------------------------------------------------------ 优惠券并发
def test_one_coupon_cannot_be_used_by_concurrent_orders(client, db, monkeypatch):
    """同一张券并发下两单：没有行锁时，两边都读到「未使用」，两单都拿到优惠。"""
    from app import shop_service

    code = f"C_RACE_{uuid.uuid4().hex[:6].upper()}"
    data_of(client.post("/shop/admin/coupons", json={
        "code": code, "name": "并发测试券", "type": "full_reduce",
        "threshold": "1", "amount": "1", "days": 10, "total": 5, "per_user_limit": 1}))
    data_of(client.post(f"/shop/admin/coupons/{code}/grant", json={"user_ids": ["u1003"]}))
    _set_stock(db, "SKU10003-01", 50)
    _set_stock(db, "SKU10002-01", 50)

    original = shop_service._compute_amounts

    def slow_compute(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(0.4)  # 卡在「已查券、未提交」之间
        return result

    monkeypatch.setattr(shop_service, "_compute_amounts", slow_compute)
    gate = threading.Barrier(2)

    def order(sku_code):
        gate.wait()
        return client.post("/shop/orders", json={
            "user_id": "u1003", "coupon_code": code,
            "items": [{"sku_code": sku_code, "quantity": 1}]}).status_code

    # 两单买不同商品：同一 SKU 的行锁会把两单被动串行，掩盖券上的竞态
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(order, c) for c in ("SKU10003-01", "SKU10002-01")]
        codes = [f.result() for f in futures]
    assert sorted(codes) == [200, 409], codes


# ------------------------------------------------------------------ 幂等键按用户隔离
def test_idempotency_key_is_not_shared_across_users(client, db):
    _set_stock(db, "SKU10006-01", 20)
    key = f"shared-{uuid.uuid4().hex[:8]}"
    a = _buy(client, "u1001", "SKU10006-01", pay=False, headers={"Idempotency-Key": key})
    b = client.post("/shop/orders", headers={"Idempotency-Key": key}, json={
        "user_id": "u1002", "items": [{"sku_code": "SKU10006-01", "quantity": 1}]})
    assert a["order_id"] not in b.text, "不能把 A 的订单回放给 B"
    # A 自己重试仍回放同一张单
    again = _buy(client, "u1001", "SKU10006-01", pay=False, headers={"Idempotency-Key": key})
    assert again["order_id"] == a["order_id"]
