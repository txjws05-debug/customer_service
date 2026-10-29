"""幂等记录表：请求级状态机。

`orders.request_id` 唯一索引只能保证「不会有两张订单」，保证不了下面三件事，
而这三件事都会真实发生：

1. 同一个请求被执行两遍（并发时两个请求都跑完库存与优惠券校验，输的一方
   在唯一冲突时才回滚，白占行锁）；
2. 失败后能不能立刻重试（若键卡在 processing，用户改完地址再提交会被自己挡住）；
3. 进程在「占了键但还没提交」时被杀，这个键会不会永久卡死。

这里逐条钉住：成功 → succeeded、失败 → failed（可立即重试）、
被杀 → 租约到期后可被重新抢占。
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

from sqlalchemy import func, select, text

from app import idempotency, models
from app import shop_rules as rules
from app.database import SessionLocal

SKU = "SKU10006-01"
SCOPE = "order"


def _reset_stock(db, stock: int) -> None:
    db.execute(text("UPDATE product_skus SET stock=:s WHERE sku_code=:c"),
               {"s": stock, "c": SKU})
    db.commit()


def _stock(db) -> int:
    db.expire_all()
    return db.scalar(select(models.ProductSku.stock)
                     .where(models.ProductSku.sku_code == SKU))


def _place(client, key: str | None, quantity: int = 1):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/shop/orders", headers=headers, json={
        "user_id": "u1001",
        "items": [{"sku_code": SKU, "quantity": quantity}],
    })


def _record(db, key: str):
    db.expire_all()
    return db.execute(text(
        "SELECT status, result_ref, reason, attempts FROM idempotency_key "
        "WHERE scope=:s AND key=:k"), {"s": SCOPE, "k": key}).first()


def _plant(db, key: str, status: str, lease_offset_seconds: int) -> None:
    """手工种一条记录，模拟「另一个进程留下了这个状态」。"""
    now = rules.now()
    db.execute(text(
        "INSERT INTO idempotency_key "
        "(scope, key, status, attempts, lease_until, created_at, updated_at) "
        "VALUES (:s, :k, :st, 1, :lease, :now, :now)"), {
        "s": SCOPE, "k": key, "st": status,
        "lease": now + timedelta(seconds=lease_offset_seconds),
        "now": now,
    })
    db.commit()


def _orders_with_key(db, key: str) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(models.Order)
                     .where(models.Order.request_id == key))


# --------------------------------------------------------------- 成功路径
def test_success_records_result_ref(client, db):
    _reset_stock(db, 20)
    key = "idem-success-1"
    response = _place(client, key)
    assert response.status_code == 200, response.text
    order_id = response.json()["data"]["order_id"]

    status, result_ref, reason, attempts = _record(db, key)
    assert status == "succeeded"
    assert result_ref == order_id, "result_ref 必须指向真实订单，回放才有依据"
    assert reason is None
    assert attempts == 1


def test_succeeded_key_replays_without_touching_stock(client, db):
    _reset_stock(db, 20)
    key = "idem-replay-1"
    first = _place(client, key).json()["data"]["order_id"]
    stock_after_first = _stock(db)

    second = _place(client, key)
    assert second.status_code == 200
    assert second.json()["data"]["order_id"] == first
    assert _stock(db) == stock_after_first, "回放不能再扣一次库存"
    assert _record(db, key)[3] == 1, "回放不该增加 attempts"


# --------------------------------------------------------------- 失败后可重试
def test_failure_marks_failed_and_allows_immediate_retry(client, db):
    """库存不足失败后，同一个键必须能立刻重试 —— 不必等 30 秒租约。"""
    key = "idem-retry-1"
    _reset_stock(db, 0)

    failed = _place(client, key)
    assert failed.status_code == 409, failed.text
    status, result_ref, reason, _ = _record(db, key)
    assert status == "failed", "失败不落 failed，键会卡在 processing 直到租约过期"
    assert result_ref is None
    assert reason and "库存不足" in reason, f"失败原因要能直接看懂：{reason}"

    # 补货后同一个键重试
    _reset_stock(db, 5)
    ok = _place(client, key)
    assert ok.status_code == 200, ok.text
    assert _record(db, key)[0] == "succeeded"
    assert _record(db, key)[3] == 2, "重试应累加 attempts，便于看出被拒过几次"


def test_failure_leaves_no_ghost_order(client, db):
    """库存不足不能留下订单行 —— 否则「失败」的请求会变成一张真订单。"""
    key = "idem-ghost-1"
    _reset_stock(db, 0)
    assert _place(client, key).status_code == 409
    assert _orders_with_key(db, key) == 0


# --------------------------------------------------------------- 处理中 / 被杀
def test_in_progress_key_is_rejected_not_duplicated(client, db, monkeypatch):
    """等了仍无结果 = 确实还在处理：回 409，且绝不建单。"""
    # 默认等待 1.5s，这里缩到 0.2s —— 测的是「等完仍处理中就拒」，
    # 不是「等了多久」。
    monkeypatch.setattr(idempotency, "IN_PROGRESS_WAIT_SECONDS", 0.2)
    key = "idem-inprogress-1"
    _reset_stock(db, 20)
    _plant(db, key, "processing", lease_offset_seconds=60)

    response = _place(client, key)
    assert response.status_code == 409, response.text
    assert "正在处理中" in response.json()["message"]
    assert _orders_with_key(db, key) == 0


def test_in_progress_waits_then_replays(db):
    """第一次请求还在跑时，重试应当等到它成功并回放，而不是报错。

    这是「处理中直接回 409」的替代方案：用户重试的真实场景里，第一次往往
    已经成功、只是响应没回来。直接报错会让他换个新键再点一次 —— 那才是重复下单。
    """
    key = "idem-wait-1"
    _plant(db, key, "processing", lease_offset_seconds=60)

    def flip_to_success() -> None:
        time.sleep(0.3)
        with SessionLocal() as session:
            session.execute(text(
                "UPDATE idempotency_key SET status='succeeded', result_ref='SO-WAIT-1' "
                "WHERE scope='order' AND key=:k"), {"k": key})
            session.commit()

    threading.Thread(target=flip_to_success, daemon=True).start()

    acquired = idempotency.try_acquire(db, SCOPE, key, wait_seconds=2.0)
    assert acquired.state == "succeeded"
    assert acquired.result_ref == "SO-WAIT-1"


def test_expired_lease_can_be_reacquired(client, db):
    """租约过期 = 原进程已死：后来者必须能接管，否则这个键永久卡死。"""
    key = "idem-dead-process-1"
    _reset_stock(db, 20)
    _plant(db, key, "processing", lease_offset_seconds=-1)

    response = _place(client, key)
    assert response.status_code == 200, response.text
    status, result_ref, _, attempts = _record(db, key)
    assert status == "succeeded"
    assert result_ref == response.json()["data"]["order_id"]
    assert attempts == 2, "接管也应累加 attempts"


# --------------------------------------------------------------- 兼容性
def test_without_key_table_stays_empty(client, db):
    """不传幂等键 = 老调用方：一行记录都不该产生。"""
    _reset_stock(db, 20)
    db.execute(text("DELETE FROM idempotency_key"))
    db.commit()

    assert _place(client, None).status_code == 200
    db.expire_all()
    assert db.scalar(text("SELECT count(*) FROM idempotency_key")) == 0
