"""运营管理端 API 的集成测试（真库 + 真 HTTP）。

重点是**跨角色一致性**：后台推进的状态必须就是用户端看到的状态，
因为两边共用同一套状态机（shop_rules）——这是这套设计最值得验证的一点。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

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


def _place_and_pay(client, user_id: str, sku_code: str, quantity: int = 1) -> str:
    _clear_cart(client, user_id)
    client.post(f"/shop/users/{user_id}/cart",
                json={"sku_code": sku_code, "quantity": quantity})
    created = data_of(client.post("/shop/orders", json={"user_id": user_id}))
    data_of(client.post(f"/shop/orders/{created['order_id']}/pay", json={"channel": "wechat"}))
    return created["order_id"]


# ============================================================ 订单与履约
def test_admin_order_list_with_status_counts(client, db):
    listed = data_of(client.get("/shop/admin/orders", params={"page_size": 100}))
    total_orders = db.scalar(select(func.count(models.Order.id)))
    assert listed["total"] == int(total_orders)
    assert sum(listed["status_counts"].values()) == int(total_orders)
    assert listed["orders"], "种子数据里应当有订单"

    # 按状态筛选
    finished = data_of(client.get("/shop/admin/orders",
                                  params={"status": rules.STATUS_FINISHED}))
    assert all(o["status"] == rules.STATUS_FINISHED for o in finished["orders"])

    # 按用户筛选
    by_user = data_of(client.get("/shop/admin/orders", params={"user_id": "u1001"}))
    assert all(o["user_id"] == "u1001" for o in by_user["orders"])


def test_admin_fulfillment_chain_reaches_user_side(client, db):
    """后台发货+推进，用户端应当能看到「待收货」并完成收货。"""
    order_id = _place_and_pay(client, "u1001", "SKU10003-01", 1)

    shipped = data_of(client.post(f"/shop/admin/orders/{order_id}/ship",
                                  json={"company": "京东物流", "tracking_number": "JD99887766"}))
    assert shipped["status"] == rules.STATUS_PENDING_PICKUP
    assert shipped["logistics_company"] == "京东物流"
    assert shipped["tracking_number"] == "JD99887766"

    transit = data_of(client.post(f"/shop/admin/orders/{order_id}/advance", json={}))
    assert transit["status"] == rules.STATUS_IN_TRANSIT

    arriving = data_of(client.post(f"/shop/admin/orders/{order_id}/advance", json={}))
    assert arriving["status"] == rules.STATUS_PENDING_RECEIVE

    # 用户端：能看到物流轨迹、并且可以确认收货
    user_view = data_of(client.get(f"/shop/orders/{order_id}"))
    assert user_view["status"] == rules.STATUS_PENDING_RECEIVE
    assert user_view["can_receive"] is True
    assert user_view["tracking_number"] == "JD99887766"

    logistics = data_of(client.get(f"/orders/{order_id}/logistics"))
    assert logistics["tracking_number"] == "JD99887766"
    assert len(logistics["traces"]) >= 3   # 出库 + 揽收 + 派送

    received = data_of(client.post(f"/shop/orders/{order_id}/receive"))
    assert received["status"] == rules.STATUS_FINISHED
    # 后台再推进就该被拒绝
    blocked = client.post(f"/shop/admin/orders/{order_id}/advance", json={})
    assert blocked.status_code == 409


def test_admin_cannot_ship_unpaid_order(client):
    _clear_cart(client, "u1002")
    client.post("/shop/users/u1002/cart", json={"sku_code": "SKU10003-01", "quantity": 1})
    created = data_of(client.post("/shop/orders", json={"user_id": "u1002"}))  # 未支付

    response = client.post(f"/shop/admin/orders/{created['order_id']}/ship", json={})
    assert response.status_code == 409
    assert "无法发货" in response.json()["message"]


# ============================================================ 售后审核台
def test_admin_after_sale_desk_flow(client):
    order_id = _place_and_pay(client, "u1003", "SKU10003-01", 1)
    ticket = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1003", "type": "refund_only", "reason": "买错了"}))
    ticket_no = ticket["ticket_no"]

    desk = data_of(client.get("/shop/admin/after-sales", params={"status": rules.AS_SUBMITTED}))
    assert any(t["ticket_no"] == ticket_no for t in desk["tickets"])

    approved = data_of(client.post(f"/shop/admin/after-sales/{ticket_no}/approve",
                                   json={"remark": "同意退款"}))
    assert approved["status"] == rules.AS_APPROVED

    completed = data_of(client.post(f"/shop/admin/after-sales/{ticket_no}/complete",
                                    json={"remark": "已退款"}))
    assert completed["status"] == rules.AS_COMPLETED
    assert completed["remark"] == "已退款"


def test_admin_reject_after_sale_keeps_order_usable(client):
    order_id = _place_and_pay(client, "u1003", "SKU10003-01", 1)
    ticket = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1003", "type": "refund_only", "reason": "随便试试"}))
    rejected = data_of(client.post(f"/shop/admin/after-sales/{ticket['ticket_no']}/reject",
                                   json={"remark": "不符合售后条件"}))
    assert rejected["status"] == rules.AS_REJECTED
    assert rejected["can_cancel"] is False

    # 被驳回的工单不再算「进行中」，用户可以重新申请
    again = data_of(client.post(f"/shop/orders/{order_id}/after-sales", json={
        "user_id": "u1003", "type": "refund_only", "reason": "商品有质量问题"}))
    assert again["ticket_no"] != ticket["ticket_no"]


# ============================================================ 库存
def test_admin_stock_update_writes_inventory_log(client, db):
    sku_code = "SKU10004-02"
    before = db.scalar(select(models.ProductSku.stock).filter(
        models.ProductSku.sku_code == sku_code))

    updated = data_of(client.patch(f"/shop/admin/skus/{sku_code}/stock",
                                   json={"stock": 33, "reason": "春节补货"}))
    assert updated["stock"] == 33
    assert updated["change"] == 33 - int(before)

    db.expire_all()
    log = db.scalar(
        select(models.InventoryLog)
        .filter(models.InventoryLog.reason == "春节补货")
        .order_by(models.InventoryLog.id.desc()))
    assert log is not None and log.change == updated["change"] and log.stock_after == 33

    # 用户端看到的库存同步变化
    detail = data_of(client.get("/shop/products/SKU10004"))
    sku = next(s for s in detail["skus"] if s["sku_code"] == sku_code)
    assert sku["stock"] == 33


def test_admin_stock_update_rejects_no_change(client):
    response = client.patch("/shop/admin/skus/SKU10004-02/stock",
                            json={"stock": 33})
    assert response.status_code == 400
    assert "没有变化" in response.json()["message"]


def test_admin_low_stock_alert(client):
    alerts = data_of(client.get("/shop/admin/low-stock", params={"threshold": 10}))
    assert isinstance(alerts, list)
    assert all(item["stock"] <= 10 for item in alerts)


# ============================================================ 优惠券
def test_admin_create_and_grant_coupon(client):
    created = data_of(client.post("/shop/admin/coupons", json={
        "code": "C_TEST20", "name": "测试满200减20", "type": "full_reduce",
        "threshold": "200", "amount": "20", "days": 10, "total": 5, "per_user_limit": 1}))
    assert created["code"] == "C_TEST20"
    assert created["claimed"] == 0
    assert created["used_count"] == 0

    # 重复券码必须被拒
    dup = client.post("/shop/admin/coupons", json={
        "code": "C_TEST20", "name": "重复", "type": "full_reduce",
        "threshold": "200", "amount": "20"})
    assert dup.status_code == 409

    granted = data_of(client.post("/shop/admin/coupons/C_TEST20/grant",
                                  json={"user_ids": ["u1001", "u1002", "nobody"]}))
    assert granted["granted"] == 2
    assert granted["skipped"] == ["nobody"]

    # 超过每人限领 → 跳过而不是报错
    again = data_of(client.post("/shop/admin/coupons/C_TEST20/grant",
                                json={"user_ids": ["u1001"]}))
    assert again["granted"] == 0
    assert again["skipped"] == ["u1001"]

    # 用户端能看到这张券
    mine = data_of(client.get("/shop/users/u1001/coupons"))
    assert any(c["code"] == "C_TEST20" for c in mine["coupons"])

    admin_view = data_of(client.get("/shop/admin/coupons"))
    row = next(c for c in admin_view if c["code"] == "C_TEST20")
    assert row["claimed"] == 2


def test_admin_coupon_create_validates_type(client):
    response = client.post("/shop/admin/coupons", json={
        "code": "C_BAD", "name": "缺参数", "type": "full_reduce", "threshold": "100"})
    assert response.status_code == 400
    assert "amount" in response.json()["message"]


# ============================================================ 看板
def test_admin_stats_dashboard(client, db):
    stats = data_of(client.get("/shop/admin/stats"))

    assert Decimal(stats["gmv"]) > 0, "历史订单已回填支付时间，GMV 应大于 0"
    assert stats["paid_order_count"] > 0
    assert sum(stats["status_counts"].values()) == int(
        db.scalar(select(func.count(models.Order.id))))
    assert Decimal(stats["after_sale_rate"]) >= 0
    assert stats["user_count"] == 3
    assert stats["product_count"] >= 6
    assert stats["top_products"], "应当有热销榜"
    assert all(p["quantity"] > 0 for p in stats["top_products"])
    assert stats["coupon_issued"] >= 5      # 种子给用户发的券
    assert isinstance(stats["low_stock"], list)
