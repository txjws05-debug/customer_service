"""退款流水：钱退了没有，必须能在库里查到。

此前系统里没有退款这本账：取消一笔已付款订单只归还库存和优惠券，支付流水仍是
success；售后完成也只改工单状态。线上因此出现了「已取消、已付款、无任何退款记录」
的订单（3 笔共 ¥9,996）。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app import after_sale_service as after_sale
from app import models
from app import shop_rules as rules


def data_of(response) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _make_order(client, user_id: str, sku_code: str, quantity: int = 1,
                pay: bool = True) -> dict:
    cart = data_of(client.get(f"/shop/users/{user_id}/cart"))
    for item in cart["items"]:
        client.delete(f"/shop/users/{user_id}/cart/{item['item_id']}")
    client.post(f"/shop/users/{user_id}/cart",
                json={"sku_code": sku_code, "quantity": quantity})
    created = data_of(client.post("/shop/orders", json={"user_id": user_id}))
    if pay:
        data_of(client.post(f"/shop/orders/{created['order_id']}/pay",
                            json={"channel": "wechat"}))
    return created


def _order(db, order_id: str) -> models.Order:
    db.expire_all()
    return db.scalar(select(models.Order).filter(models.Order.order_id == order_id))


def _refunds(db, order: models.Order) -> list:
    return list(db.scalars(select(models.Refund).filter(models.Refund.order_id == order.id)))


def _payment(db, order: models.Order) -> models.Payment:
    return db.scalar(select(models.Payment).filter(models.Payment.order_id == order.id))


def test_cancel_paid_order_refunds_in_full(client, db):
    created = _make_order(client, "u1001", "SKU10003-01", 1)
    result = data_of(client.post(f"/shop/orders/{created['order_id']}/cancel",
                                 json={"reason": "不想要了"}))
    order = _order(db, created["order_id"])
    assert result["status"] == rules.STATUS_CANCELED
    assert Decimal(result["refund_amount"]) == order.payable > 0

    refunds = _refunds(db, order)
    assert len(refunds) == 1
    assert refunds[0].amount == order.payable
    assert refunds[0].source == "order_cancel"
    assert _payment(db, order).status == "refunded"


def test_cancel_unpaid_order_has_nothing_to_refund(client, db):
    created = _make_order(client, "u1001", "SKU10003-01", 1, pay=False)
    result = data_of(client.post(f"/shop/orders/{created['order_id']}/cancel",
                                 json={"reason": "拍错了"}))
    assert Decimal(result["refund_amount"]) == 0
    assert _refunds(db, _order(db, created["order_id"])) == []


def test_completed_after_sale_writes_refund(client, db):
    """部分退款：记一笔退款，支付流水仍为 success（没退完）。"""
    created = _make_order(client, "u1001", "SKU10003-01", 2)
    ticket = data_of(client.post(f"/shop/orders/{created['order_id']}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "少发一件",
        "refund_amount": "10.00"}))
    after_sale.review_ticket(db, ticket["ticket_no"], approved=True)
    after_sale.complete_after_sale(db, ticket["ticket_no"], remark="已原路退款")

    order = _order(db, created["order_id"])
    refunds = _refunds(db, order)
    assert [(r.amount, r.source, r.ticket_no) for r in refunds] == [
        (Decimal("10.00"), "after_sale", ticket["ticket_no"])]
    assert _payment(db, order).status == "success"
