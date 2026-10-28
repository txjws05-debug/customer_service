"""下单幂等：同一个 Idempotency-Key 只能产生一张订单。

为什么这条必须有：
用户手抖点两次「提交订单」、或者网关重试，都会让同一个请求到达两次。
没有幂等键时后果是两张订单、两份库存、两次结算 —— 这是钱上的错。

实现上分两层，缺一不可：
- 应用层：入口先按 request_id 查一次，命中就直接回放（挡住绝大多数重复）；
- 数据库层：`orders.request_id` 唯一索引（挡住并发穿透，应用层的查-插之间有空隙）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select, text

from app import models

SKU = "SKU10006-01"


def _reset_stock(db, stock: int = 20) -> None:
    db.execute(text("UPDATE product_skus SET stock=:s WHERE sku_code=:c"),
               {"s": stock, "c": SKU})
    db.commit()


def _stock(db) -> int:
    return db.scalar(select(models.ProductSku.stock)
                     .where(models.ProductSku.sku_code == SKU))


def _orders_with_key(db, key: str) -> int:
    return db.scalar(select(func.count()).select_from(models.Order)
                     .where(models.Order.request_id == key))


def _place(client, key: str | None = None, quantity: int = 1):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/shop/orders", headers=headers, json={
        "user_id": "u1001",
        "items": [{"sku_code": SKU, "quantity": quantity}],
    })


def _data(response) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def test_same_key_returns_same_order_and_deducts_once(client, db):
    _reset_stock(db, 20)
    before = _stock(db)

    first = _data(_place(client, "key-sequential-1"))
    second = _data(_place(client, "key-sequential-1"))

    assert first["order_id"] == second["order_id"], "同一幂等键必须回放同一张订单"
    assert _orders_with_key(db, "key-sequential-1") == 1
    assert _stock(db) == before - 1, "只应扣一次库存"


def test_different_keys_create_two_orders(client, db):
    _reset_stock(db, 20)
    before = _stock(db)

    a = _data(_place(client, "key-a"))
    b = _data(_place(client, "key-b"))

    assert a["order_id"] != b["order_id"]
    assert _stock(db) == before - 2


def test_without_key_keeps_legacy_behaviour(client, db):
    """不传幂等键时行为不变：两次就是两张单（兼容老调用方）。"""
    _reset_stock(db, 20)
    a = _data(_place(client))
    b = _data(_place(client))
    assert a["order_id"] != b["order_id"]


def test_concurrent_same_key_creates_one_order(client, db):
    key = "key-concurrent-1"
    _reset_stock(db, 20)
    before = _stock(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _place(client, key), range(2)))

    for r in results:
        _data(r)
    assert _orders_with_key(db, key) == 1, "并发下唯一索引必须兜住"
    assert _stock(db) == before - 1
