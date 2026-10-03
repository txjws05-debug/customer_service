"""交易域 API 的集成测试（真库 + 真 HTTP 层）。

覆盖目标：
1. 完整交易闭环：加购 → 结算预览 → 下单 → 支付 → 发货(模拟运营端) → 收货 → 得积分；
2. 副作用正确：库存扣减/归还、优惠券占用/归还、积分流水、订单状态日志；
3. 非法操作被挡住：重复支付、已完成订单取消、越权地址、库存不足、未登录用户；
4. 兼容性：既有只读接口（客服 Agent 在用）不受影响。

发货属于运营端（下一切片），这里直接在库里推进状态来验证用户侧链路。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app import models
from app import shop_rules as rules


def data_of(response) -> dict:
    """取出 ApiResponse 信封里的 data，顺便断言请求成功。"""
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _stock(db, sku_code: str) -> int:
    sku = db.scalar(select(models.ProductSku).filter(models.ProductSku.sku_code == sku_code))
    assert sku is not None
    return sku.stock


def _clear_cart(client, user_id: str) -> None:
    """清空购物车：用例之间共享同一个库，开始前先归零避免互相干扰。"""
    cart = data_of(client.get(f"/shop/users/{user_id}/cart"))
    for item in cart["items"]:
        client.delete(f"/shop/users/{user_id}/cart/{item['item_id']}")


def _ship_order(db, order_id: str) -> None:
    """模拟运营端发货：待发货 → 待揽收 → 运输中 → 待收货。"""
    order = db.scalar(select(models.Order).filter(models.Order.order_id == order_id))
    assert order is not None
    order.status = rules.STATUS_PENDING_RECEIVE
    order.status_desc = rules.describe(rules.STATUS_PENDING_RECEIVE)
    order.shipped_at = rules.now()
    db.add(models.LogisticsRecord(
        order_id=order.id, logistics_company="顺丰速运",
        tracking_number=f"SF{order.id:010d}", status="派送中",
        status_desc="快件已到达派送站点。", updated_at=rules.now(),
    ))
    db.commit()


# ============================================================ 商品与搜索
def test_categories_and_product_search(client):
    categories = data_of(client.get("/shop/categories"))
    names = [c["name"] for c in categories]
    assert "手机数码" in names
    assert all(c["product_count"] >= 0 for c in categories)

    result = data_of(client.get("/shop/products", params={"q": "iPhone"}))
    assert result["total"] == 1
    assert result["items"][0]["product_id"] == "SKU10001"
    assert result["items"][0]["category"] == "手机数码"

    # 排序与价格区间
    cheap = data_of(client.get("/shop/products", params={
        "max_price": 200, "sort": "price_asc", "page_size": 50}))
    prices = [Decimal(item["price"]) for item in cheap["items"]]
    assert prices == sorted(prices)
    assert all(p <= Decimal("200") for p in prices)


def test_product_detail_lists_skus(client):
    detail = data_of(client.get("/shop/products/SKU10001"))
    assert detail["title"].startswith("iPhone 15 Pro")
    assert len(detail["skus"]) == 3
    assert detail["skus"][0]["sku_code"] == "SKU10001-01"
    assert detail["skus"][0]["spec"]["容量"] == "256GB"


# ============================================================ 购物车
def test_cart_add_update_remove(client):
    # u1002 用低价商品，避免与其它用例抢库存
    added = data_of(client.post("/shop/users/u1002/cart",
                                json={"sku_code": "SKU10003-01", "quantity": 2}))
    assert added["total_quantity"] == 2
    assert Decimal(added["selected_amount"]) == Decimal("29.80")
    item_id = added["items"][0]["item_id"]

    # 同规格再加购 → 数量累加而不是新增一行
    again = data_of(client.post("/shop/users/u1002/cart",
                                json={"sku_code": "SKU10003-01", "quantity": 1}))
    assert len(again["items"]) == 1
    assert again["items"][0]["quantity"] == 3

    updated = data_of(client.patch(f"/shop/users/u1002/cart/{item_id}",
                                   json={"quantity": 5, "selected": False}))
    assert updated["items"][0]["quantity"] == 5
    assert updated["items"][0]["selected"] is False
    assert updated["selected_amount"] == "0.00"

    removed = data_of(client.delete(f"/shop/users/u1002/cart/{item_id}"))
    assert removed["items"] == []


def test_cart_rejects_bad_sku_and_missing_user(client):
    assert client.post("/shop/users/u1001/cart",
                       json={"sku_code": "NOT-EXIST", "quantity": 1}).status_code == 404
    assert client.get("/shop/users/nobody/cart").status_code == 404


# ============================================================ 结算算钱
def test_preview_applies_coupon_freight_and_membership(client):
    client.post("/shop/users/u1003/cart", json={"sku_code": "SKU10004-01", "quantity": 1})
    # u1003 是 PLUS：免运费 + 9 折券（满 199 可用）
    preview = data_of(client.post("/shop/users/u1003/cart/preview",
                                  json={"coupon_code": "C_9OFF"}))
    assert Decimal(preview["goods_amount"]) == Decimal("2999.00")
    assert Decimal(preview["discount_amount"]) == Decimal("299.90")   # 9 折
    assert Decimal(preview["freight_amount"]) == Decimal("0")         # PLUS 免运费
    assert Decimal(preview["pay_amount"]) == Decimal("2699.10")
    assert preview["is_plus"] is True
    assert preview["receiver_address"]                       # 自动带出默认地址


def test_preview_reports_coupon_below_threshold(client):
    # 清除 u1002 购物车残留，再加一个 14.9 元的商品
    cart = data_of(client.get("/shop/users/u1002/cart"))
    for item in cart["items"]:
        client.delete(f"/shop/users/u1002/cart/{item['item_id']}")
    client.post("/shop/users/u1002/cart", json={"sku_code": "SKU10003-01", "quantity": 1})

    preview = data_of(client.post("/shop/users/u1002/cart/preview",
                                  json={"coupon_code": "C_NEW10"}))
    assert Decimal(preview["discount_amount"]) == Decimal("0")
    assert "门槛" in preview["coupon_message"]
    # 普通会员且未满 99 元 → 8 元运费
    assert Decimal(preview["freight_amount"]) == Decimal("8")
    assert Decimal(preview["pay_amount"]) == Decimal("22.90")


def test_preview_with_empty_cart_is_rejected(client):
    _clear_cart(client, "u1003")
    response = client.post("/shop/users/u1003/cart/preview", json={})
    assert response.status_code == 409
    assert "勾选" in response.json()["message"]


# ============================================================ 完整交易闭环
def test_full_purchase_flow(client, db):
    sku_code = "SKU10005-01"
    _clear_cart(client, "u1003")
    stock_before = _stock(db, sku_code)

    # 1) 加购 + 预览
    client.post("/shop/users/u1003/cart", json={"sku_code": sku_code, "quantity": 2})
    preview = data_of(client.post("/shop/users/u1003/cart/preview", json={}))
    assert Decimal(preview["goods_amount"]) == Decimal("798.00")

    # 2) 下单（占用库存 + 清空购物车勾选项）
    created = data_of(client.post("/shop/orders", json={"user_id": "u1003"}))
    order_id = created["order_id"]
    assert created["status"] == rules.STATUS_PENDING_PAY
    assert Decimal(created["pay_amount"]) == Decimal("798.00")
    assert _stock(db, sku_code) == stock_before - 2
    assert data_of(client.get("/shop/users/u1003/cart"))["items"] == []

    # 3) 待付款时可取消，但先支付
    detail = data_of(client.get(f"/shop/orders/{order_id}"))
    assert detail["can_pay"] is True and detail["can_cancel"] is True
    assert detail["items"][0]["spec_text"] == "颜色:奶白色 容量:5L"

    paid = data_of(client.post(f"/shop/orders/{order_id}/pay", json={"channel": "alipay"}))
    assert paid["status"] == rules.STATUS_PENDING_SHIP
    assert paid["trade_no"].startswith("PAY")

    # 4) 重复支付必须被挡住
    again = client.post(f"/shop/orders/{order_id}/pay", json={"channel": "alipay"})
    assert again.status_code == 409
    assert "无法支付" in again.json()["message"]

    # 5) 运营端发货（本切片直接改库）→ 用户确认收货
    _ship_order(db, order_id)
    points_before = db.scalar(
        select(models.User.points).filter(models.User.user_id == "u1003"))

    received = data_of(client.post(f"/shop/orders/{order_id}/receive"))
    assert received["status"] == rules.STATUS_FINISHED
    # u1003 是 PLUS：798 元 → 798 分 ×2 = 1596
    assert received["earned_points"] == 1596

    db.expire_all()
    points_after = db.scalar(
        select(models.User.points).filter(models.User.user_id == "u1003"))
    assert points_after == (points_before or 0) + 1596

    # 6) 状态日志完整（创建、支付、收货），可审计
    final = data_of(client.get(f"/shop/orders/{order_id}"))
    transitions = [log["to_status"] for log in final["status_logs"]]
    assert transitions == [rules.STATUS_PENDING_PAY, rules.STATUS_PENDING_SHIP,
                           rules.STATUS_FINISHED]
    assert final["paid_at"] and final["received_at"]
    assert final["can_pay"] is False and final["can_cancel"] is False

    # 7) 已完成订单不能再取消
    assert client.post(f"/shop/orders/{order_id}/cancel", json={}).status_code == 409

    # 8) 积分流水带上了订单号
    points = data_of(client.get("/shop/users/u1003/points"))
    assert points["points"] == points_after
    assert points["ledger"][0]["order_id"] == order_id
    assert points["next_level_points"] > 0


# ============================================================ 取消与归还
def test_cancel_restores_stock_and_coupon(client, db):
    sku_code = "SKU10002-01"
    _clear_cart(client, "u1001")
    stock_before = _stock(db, sku_code)

    # 4 × 149 = 596 元，刚好越过「满 500 减 50」的门槛
    client.post("/shop/users/u1001/cart", json={"sku_code": sku_code, "quantity": 4})
    created = data_of(client.post("/shop/orders", json={
        "user_id": "u1001", "coupon_code": "C_500_50"}))
    order_id = created["order_id"]
    assert Decimal(created["discount_amount"]) == Decimal("50.00")
    assert _stock(db, sku_code) == stock_before - 4

    # 优惠券已被占用
    coupons = data_of(client.get("/shop/users/u1001/coupons"))
    used = [c for c in coupons["coupons"] if c["code"] == "C_500_50"]
    assert used and used[0]["status"] == "used"

    cancelled = data_of(client.post(f"/shop/orders/{order_id}/cancel",
                                    json={"reason": "不想要了"}))
    assert cancelled["status"] == rules.STATUS_CANCELED

    # 库存归还、优惠券退回可用
    db.expire_all()
    assert _stock(db, sku_code) == stock_before
    coupons = data_of(client.get("/shop/users/u1001/coupons"))
    rolled_back = [c for c in coupons["coupons"] if c["code"] == "C_500_50"]
    assert rolled_back and rolled_back[0]["status"] == "unused"

    # 归还后应能立刻再用：重新加购后这张券可以正常抵扣
    client.post("/shop/users/u1001/cart", json={"sku_code": sku_code, "quantity": 4})
    reuse = data_of(client.post("/shop/users/u1001/cart/preview",
                                json={"coupon_code": "C_500_50"}))
    assert Decimal(reuse["discount_amount"]) == Decimal("50.00")
    _clear_cart(client, "u1001")


def test_order_rejects_coupon_below_threshold(client):
    """下单时券不满门槛要明确失败，不能让用户以为用了券却按原价付款。"""
    _clear_cart(client, "u1002")
    client.post("/shop/users/u1002/cart", json={"sku_code": "SKU10003-01", "quantity": 1})
    response = client.post("/shop/orders", json={
        "user_id": "u1002", "coupon_code": "C_NEW10"})  # 满 100 才可用，这里只有 14.9
    assert response.status_code == 409
    assert "门槛" in response.json()["message"]
    # 失败不留副作用：购物车还在
    assert len(data_of(client.get("/shop/users/u1002/cart"))["items"]) == 1
    _clear_cart(client, "u1002")


def test_order_with_someone_elses_address_is_rejected(client, db):
    other_address = db.scalar(
        select(models.Address).filter(models.Address.user_id == 1))  # u1001 的地址
    response = client.post("/shop/orders", json={
        "user_id": "u1002", "address_id": other_address.id,
        "items": [{"sku_code": "SKU10003-01", "quantity": 1}]})
    assert response.status_code == 404
    assert "收货地址" in response.json()["message"]


def test_order_rejects_insufficient_stock(client, db):
    sku = db.scalar(select(models.ProductSku).filter(
        models.ProductSku.sku_code == "SKU10006-01"))
    assert sku.stock < 99, "种子数据里 SKU10006-01 的库存应少于 99 件"
    response = client.post("/shop/orders", json={
        "user_id": "u1002",
        "items": [{"sku_code": "SKU10006-01", "quantity": 99}]})
    assert response.status_code == 409
    assert "库存不足" in response.json()["message"]
    db.expire_all()
    assert _stock(db, "SKU10006-01") == sku.stock  # 失败不留副作用


# ============================================================ 订单列表
def test_order_list_filters_by_status(client):
    listing = data_of(client.get("/shop/users/u1001/orders"))
    assert listing["user_id"] == "u1001"
    assert listing["total"] > 0

    finished = data_of(client.get("/shop/users/u1001/orders",
                                  params={"status": rules.STATUS_FINISHED}))
    assert all(o["status"] == rules.STATUS_FINISHED for o in finished["orders"])


# ============================================================ 兼容性
def test_legacy_readonly_endpoints_still_work(client):
    """既有接口是客服 Agent 在用的，绝不能因为加了交易域而受影响。"""
    order = data_of(client.get("/orders/A20260410001"))
    assert order["order_id"] == "A20260410001"
    assert order["status"] == "待发货"

    status = data_of(client.get("/orders/A20260408002/status"))
    assert status["status"] == "运输中"

    logistics = data_of(client.get("/orders/A20260408002/logistics"))
    assert logistics["tracking_number"] == "JD000123456789"

    product = data_of(client.get("/products/SKU10001"))
    assert product["product_id"] == "SKU10001"

    user_orders = data_of(client.get("/users/u1001/orders"))
    assert user_orders["user_id"] == "u1001"
    assert len(user_orders["orders"]) > 0

    assert client.get("/health").status_code == 200
