"""并发下单的正确性：库存不能被超卖。

这条链路最容易出错的地方就在这里 —— 两个人同时买最后一件，如果没有行锁，
两边都会读到"还有 1 件"，然后都下单成功，库存变成 -1。

实现要点（也是面试会被追问的点）：
- 扣库存前用 `SELECT ... FOR UPDATE` 锁住 SKU 行（见 shop_service.create_order）；
- 校验和扣减在同一个事务里，失败整体回滚；
- 提交前的库存检查基于**锁内读到的值**，不是锁外的旧值。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app import models


def data_of(response) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _place_order(client, user: str, sku_code: str):
    """下一单（直接购买 1 件），返回状态码。"""
    response = client.post("/shop/orders", json={
        "user_id": user,
        "items": [{"sku_code": sku_code, "quantity": 1}],
    })
    return response.status_code


def test_concurrent_orders_never_oversell(client, db):
    sku_code = "SKU10006-01"
    stock = 3
    concurrency = 10

    # 先用运营端把库存压到一个很小的值，制造真实的抢购场景
    data_of(client.patch(f"/shop/admin/skus/{sku_code}/stock",
                         json={"stock": stock, "reason": "并发测试准备"}))

    users = ["u1001", "u1002", "u1003"]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_place_order, client, users[index % len(users)], sku_code)
            for index in range(concurrency)
        ]
        codes = [future.result() for future in futures]

    succeeded = codes.count(200)
    rejected = codes.count(409)

    assert succeeded == stock, f"应当只有 {stock} 单成功，实际 {succeeded}（状态码：{codes}）"
    assert rejected == concurrency - stock, f"其余应当因库存不足被拒：{codes}"

    db.expire_all()
    final = db.scalar(
        select(models.ProductSku.stock).filter(models.ProductSku.sku_code == sku_code))
    assert final == 0, f"库存应当刚好扣完，实际 {final}"
    assert final >= 0, "库存不允许变成负数（超卖）"
