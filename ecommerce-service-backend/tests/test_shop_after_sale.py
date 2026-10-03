"""售后工单与评价的集成测试（真库 + 真 HTTP）。

售后流程里有几步属于运营端（审核、确认收到退货、完成退款）——那批接口在
下一切片的 admin_api 里。这里直接调用同一份 service 函数来推进状态，
保证用户侧链路的断言仍然是端到端的。
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


def _clear_cart(client, user_id: str) -> None:
    cart = data_of(client.get(f"/shop/users/{user_id}/cart"))
    for item in cart["items"]:
        client.delete(f"/shop/users/{user_id}/cart/{item['item_id']}")


def _stock(db, sku_code: str) -> int:
    sku = db.scalar(select(models.ProductSku).filter(models.ProductSku.sku_code == sku_code))
    assert sku is not None
    return sku.stock


def _make_order(client, user_id: str, sku_code: str, quantity: int = 1,
                pay: bool = True) -> dict:
    _clear_cart(client, user_id)
    client.post(f"/shop/users/{user_id}/cart",
                json={"sku_code": sku_code, "quantity": quantity})
    created = data_of(client.post("/shop/orders", json={"user_id": user_id}))
    if pay:
        data_of(client.post(f"/shop/orders/{created['order_id']}/pay",
                            json={"channel": "wechat"}))
    return created


# ============================================================ 售后
def test_after_sale_blocked_on_unpaid_order(client):
    created = _make_order(client, "u1001", "SKU10003-01", 1, pay=False)
    response = client.post(f"/shop/orders/{created['order_id']}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "拍错了"})
    assert response.status_code == 409
    assert "暂不支持申请售后" in response.json()["message"]


def test_refund_only_full_flow(client, db):
    created = _make_order(client, "u1001", "SKU10003-01", 2)
    order_id = created["order_id"]

    ticket = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "商品与描述不符",
        "evidence": ["https://example.com/e1.jpg"]}))
    ticket_no = ticket["ticket_no"]
    assert ticket["status"] == rules.AS_SUBMITTED
    assert ticket["type_desc"] == "仅退款（不退货）"
    assert Decimal(ticket["refund_amount"]) == Decimal(created["pay_amount"])
    assert ticket["can_cancel"] is True

    # 运营端审核通过 → 仅退款可直接完成
    after_sale.review_ticket(db, ticket_no, approved=True)
    done = after_sale.complete_after_sale(db, ticket_no, remark="已原路退款")
    assert done.status == rules.AS_COMPLETED
    assert done.can_cancel is False

    listing = data_of(client.get("/shop/users/u1001/after-sales",
                                 params={"status": rules.AS_COMPLETED}))
    assert any(t["ticket_no"] == ticket_no for t in listing["tickets"])


def test_return_refund_restores_stock(client, db):
    sku_code = "SKU10003-02"
    stock_before = _stock(db, sku_code)
    created = _make_order(client, "u1003", sku_code, 2)
    order_id = created["order_id"]
    assert _stock(db, sku_code) == stock_before - 2

    ticket = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1003", "type": "return_refund", "reason": "尺码不合适"}))
    ticket_no = ticket["ticket_no"]
    assert ticket["can_return"] is False        # 还没审核通过

    after_sale.review_ticket(db, ticket_no, approved=True)
    detail = data_of(client.get(f"/shop/after-sales/{ticket_no}"))
    assert detail["can_return"] is True         # 审核通过后可以寄回

    returning = data_of(client.post(f"/shop/after-sales/{ticket_no}/return", json={
        "tracking_number": "SF1234567890", "company": "顺丰速运"}))
    assert returning["status"] == rules.AS_RETURNING
    assert "SF1234567890" in returning["remark"]

    after_sale.receive_return(db, ticket_no)
    completed = after_sale.complete_after_sale(db, ticket_no)
    assert completed.status == rules.AS_COMPLETED

    # 退货验收完成 → 库存回滚，并留下可审计的流水
    db.expire_all()
    assert _stock(db, sku_code) == stock_before
    log = db.scalar(
        select(models.InventoryLog)
        .filter(models.InventoryLog.reason == "after_sale_return")
        .order_by(models.InventoryLog.id.desc()))
    assert log is not None and log.change == 2


def test_only_one_open_ticket_per_order(client):
    created = _make_order(client, "u1001", "SKU10003-01", 1)
    order_id = created["order_id"]
    body = {"user_id": "u1001", "type": "refund_only", "reason": "不想要了"}
    data_of(client.post(f"/shop/orders/{order_id}/after-sales", json=body))

    again = client.post(f"/shop/orders/{order_id}/after-sales", json=body)
    assert again.status_code == 409
    assert "进行中的售后单" in again.json()["message"]


def test_refund_amount_cannot_exceed_paid(client):
    created = _make_order(client, "u1001", "SKU10003-01", 1)
    response = client.post(f"/shop/orders/{created['order_id']}/after-sales", json={
        "user_id": "u1001", "type": "refund_only", "reason": "多退点",
        "refund_amount": "99999.00"})
    assert response.status_code == 400
    assert "不能超过实付金额" in response.json()["message"]


def test_canceled_ticket_allows_new_application(client):
    created = _make_order(client, "u1001", "SKU10003-01", 1)
    order_id = created["order_id"]
    body = {"user_id": "u1001", "type": "refund_only", "reason": "先申请看看"}
    ticket = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json=body))

    canceled = data_of(client.post(f"/shop/after-sales/{ticket['ticket_no']}/cancel"))
    assert canceled["status"] == rules.AS_CANCELED

    # 撤销后可以重新申请（撤销的工单不算「进行中」）
    again = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json=body))
    assert again["ticket_no"] != ticket["ticket_no"]


# ============================================================ 评价
def test_review_requires_finished_order(client):
    created = _make_order(client, "u1002", "SKU10003-01", 1)   # 已付款但未收货
    response = client.post(f"/shop/orders/{created['order_id']}/reviews", json={
        "user_id": "u1002",
        "items": [{"product_id": "SKU10003", "rating": 5, "content": "提前评价"}]})
    assert response.status_code == 409
    assert "只有已完成的订单可以评价" in response.json()["message"]


def test_review_updates_rating_and_awards_points(client, db, ship_order):
    created = _make_order(client, "u1002", "SKU10003-01", 1)
    order_id = created["order_id"]
    ship_order(order_id)
    data_of(client.post(f"/shop/orders/{order_id}/receive"))

    points_before = db.scalar(
        select(models.User.points).filter(models.User.user_id == "u1002")) or 0
    product = db.scalar(
        select(models.Product).filter(models.Product.product_id == "SKU10003"))
    count_before = product.rating_count

    reviews = data_of(client.post(f"/shop/orders/{order_id}/reviews", json={
        "user_id": "u1002",
        "items": [{"product_id": "SKU10003", "rating": 5, "content": "很暖和，回购了",
                   "images": ["https://example.com/r1.jpg"]}]}))
    assert len(reviews) == 1
    review_id = reviews[0]["id"]
    assert reviews[0]["nickname"] == "王敏"

    db.expire_all()
    # 商品评分聚合立刻更新
    product = db.scalar(
        select(models.Product).filter(models.Product.product_id == "SKU10003"))
    assert product.rating_count == count_before + 1
    assert product.rating_avg > Decimal("0")

    # 评价奖励积分（10 分/条），且与积分流水一致
    points_after = db.scalar(
        select(models.User.points).filter(models.User.user_id == "u1002"))
    assert points_after == points_before + rules.POINTS_PER_REVIEW
    points = data_of(client.get("/shop/users/u1002/points"))
    assert points["points"] == points_after
    assert any(log["reason"] == "评价奖励" for log in points["ledger"])

    # 商品评价列表
    listing = data_of(client.get("/shop/products/SKU10003/reviews"))
    assert listing["total"] >= 1
    assert listing["rating_count"] == product.rating_count

    # 追评只能一次
    appended = data_of(client.post(f"/shop/users/u1002/reviews/{review_id}/append",
                                   json={"content": "用了一个月还是很热"}))
    assert appended["append_content"] == "用了一个月还是很热"
    twice = client.post(f"/shop/users/u1002/reviews/{review_id}/append",
                        json={"content": "再来一次"})
    assert twice.status_code == 409


def test_review_rejects_product_not_in_order(client, ship_order):
    created = _make_order(client, "u1002", "SKU10003-01", 1)
    order_id = created["order_id"]
    ship_order(order_id)
    data_of(client.post(f"/shop/orders/{order_id}/receive"))

    response = client.post(f"/shop/orders/{order_id}/reviews", json={
        "user_id": "u1002",
        "items": [{"product_id": "SKU10006", "rating": 5, "content": "刷个好评"}]})
    assert response.status_code == 400
    assert "不在订单" in response.json()["message"]


def test_pending_reviews_lists_finished_orders(client, ship_order):
    created = _make_order(client, "u1003", "SKU10003-01", 1)
    order_id = created["order_id"]
    ship_order(order_id)
    data_of(client.post(f"/shop/orders/{order_id}/receive"))

    pending = data_of(client.get("/shop/users/u1003/pending-reviews"))
    assert order_id in pending["order_ids"]

    data_of(client.post(f"/shop/orders/{order_id}/reviews", json={
        "user_id": "u1003",
        "items": [{"product_id": "SKU10003", "rating": 4, "content": "还行"}]}))
    pending_after = data_of(client.get("/shop/users/u1003/pending-reviews"))
    assert order_id not in pending_after["order_ids"]
