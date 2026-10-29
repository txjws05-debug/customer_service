"""幂等键：把「这个请求是不是已经有人做过」变成一条可抢占的记录。

为什么在 `orders.request_id` 唯一索引之外还要这张表：

唯一索引只能保证「不会有两张订单」，但它挡不住下面两件事，而这两件事在并发
或重试场景里都会真实发生：

1. 两个并发请求各自完整跑一遍库存锁定与优惠券校验 —— 输的一方要等赢的一方
   提交后才因唯一冲突回滚重放，期间一直占着行锁，高峰期会放大成排队；
2. 用户看不到「正在处理」这个状态 —— 连点两次只会看到两个几乎相同的响应
   在竞速，哪次生效全凭运气，而正确反馈应该是「已在处理，请勿重复提交」。

这张表补的是「请求级」状态机：

    processing --业务成功--> succeeded（带 result_ref，供回放）
        |
        +------业务失败----> failed（可立即重试，不必等租约到期）
        |
        +------进程被杀----> 租约到期后可被重新抢占

抢占是一条 `INSERT ... ON CONFLICT` 完成的，没有「先查再插」的空隙；
三个状态之间的迁移也全部在这条语句里判断，不需要额外的分布式锁。

「处理中」为什么不直接回 409：用户点重试时，第一次请求往往**已经成功**，
只是响应还没回来。此时甩一个「处理中，请勿重复提交」的报错，用户会以为失败，
换个新的 Idempotency-Key 再点一次 —— 那才是真正的重复下单。
所以先短暂等待（默认 1.5s，够覆盖正常下单耗时），等到了就回放结果，
仍然在处理才回 409。等待有上界，不会退化成排队。
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import shop_rules as rules
from app.database import SessionLocal

logger = logging.getLogger("app.idempotency")

SCOPE_ORDER = "order"

# 处理中状态的租约。进程被 kill 后，最多等这么久就能重新抢占 ——
# 30 秒是「用户愿意重试的耐心」与「正常下单耗时」之间的折中（正常约 0.1~1s）。
LEASE_SECONDS = 30

# 「处理中」的等待窗口：够覆盖正常下单耗时（实测 15~100ms），
# 又不能长到让重复请求排队。超时即回 409。
IN_PROGRESS_WAIT_SECONDS = 1.5
_POLL_INTERVAL = 0.1

# 抢占语句。语义都在 WHERE 里：
# - 键不存在 → 插入，抢到；
# - 键是 failed → 覆盖为 processing，抢到（失败重试）；
# - 键是 processing 但租约已过 → 覆盖为 processing，抢到（原进程已死）；
# - 键是 processing 且租约未过 → WHERE 不成立，不返回行，说明别人在做；
# - 键是 succeeded → 同上，交给回放。
# 注意 ON CONFLICT DO UPDATE 会先取行锁，因此并发的一方会等待赢家提交，
# 然后按赢家提交后的状态重新判定 —— 这正是我们要的「后到者回放」。
_ACQUIRE_SQL = text(
    """
    INSERT INTO idempotency_key
        (scope, key, status, attempts, lease_until, created_at, updated_at)
    VALUES
        (:scope, :key, 'processing', 1, :lease_until, :now, :now)
    ON CONFLICT (scope, key) DO UPDATE
       SET status = 'processing',
           attempts = idempotency_key.attempts + 1,
           lease_until = :lease_until,
           updated_at = :now
     WHERE idempotency_key.status = 'failed'
        OR (idempotency_key.status = 'processing'
            AND idempotency_key.lease_until < :now)
    RETURNING id
    """
)

_READ_SQL = text(
    "SELECT status, result_ref FROM idempotency_key "
    "WHERE scope = :scope AND key = :key"
)


class Acquired(NamedTuple):
    """抢占结果。

    state:
      - acquired    本次抢到了，可以往下做业务
      - succeeded   之前已经成功过，调用方应回放 result_ref
      - in_progress 别的请求正在做，调用方应返回 409
    """

    state: str
    result_ref: str | None = None


def try_acquire(db: Session, scope: str, key: str,
                lease_seconds: int = LEASE_SECONDS,
                wait_seconds: float | None = None) -> Acquired:
    """尝试抢占幂等键。抢到与没抢到都会把当前事务收干净。"""
    if wait_seconds is None:
        wait_seconds = IN_PROGRESS_WAIT_SECONDS
    now = rules.now()
    row = db.execute(_ACQUIRE_SQL, {
        "scope": scope,
        "key": key,
        "now": now,
        "lease_until": now + timedelta(seconds=lease_seconds),
    }).first()

    if row is not None:
        # 抢占必须立刻提交：否则这条 processing 对其他请求不可见，
        # 「别人正在做」的判断就永远为假，并发会重新穿透到业务层。
        db.commit()
        return Acquired("acquired")

    # 没抢到：结束当前事务后再读，确保读到的是对方提交后的最新状态
    db.commit()

    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        current = db.execute(_READ_SQL, {"scope": scope, "key": key}).first()
        # 每轮读都是一次独立快照，读完立刻结束事务，下一轮才看得到别人的提交
        db.rollback()

        if current is None:
            # 极端竞态：刚被别人删掉（例如 cleanup）。让调用方当失败重试处理。
            return Acquired("in_progress")

        status, result_ref = current[0], current[1]
        if status == "succeeded":
            return Acquired("succeeded", result_ref)
        if status == "failed":
            # 对方失败了 —— 这个键现在可抢。递归一次且不再等待，
            # 避免两个请求互相等着对方失败。
            return try_acquire(db, scope, key, lease_seconds, wait_seconds=0)

        if time.monotonic() >= deadline:
            return Acquired("in_progress")
        time.sleep(_POLL_INTERVAL)


def mark_succeeded(db: Session, scope: str, key: str, result_ref: str) -> None:
    """标记成功。**不提交** —— 必须与业务事务同一次提交。

    如果这里自己 commit，就会出现「幂等记录说成功了、订单却没落库」的窗口：
    进程恰好在这两步之间被杀，重试会拿到一个不存在的 order_id。
    """
    db.execute(text(
        "UPDATE idempotency_key SET status = 'succeeded', result_ref = :ref, "
        "reason = NULL, lease_until = NULL, updated_at = :now "
        "WHERE scope = :scope AND key = :key"),
        {"ref": result_ref, "now": rules.now(), "scope": scope, "key": key})


def mark_failed(scope: str, key: str, reason: str) -> None:
    """标记失败，让同一个键可以立即重试。

    必须用**独立 Session**：调用点此刻刚 rollback 完业务事务，
    复用同一个 Session 写进去的记录会随下一次回滚一起消失，
    表现就是「明明失败了，键却一直卡在 processing，30 秒内不能重试」。
    """
    try:
        with SessionLocal() as session:
            session.execute(text(
                "UPDATE idempotency_key SET status = 'failed', reason = :reason, "
                "lease_until = NULL, updated_at = :now "
                "WHERE scope = :scope AND key = :key"),
                {"reason": reason[:180], "now": rules.now(),
                 "scope": scope, "key": key})
            session.commit()
    except Exception:  # noqa: BLE001
        # 写失败记录本身失败，绝不能盖住真正的业务异常 ——
        # 最坏情况只是这个键要等租约到期才能重试，不是数据错误。
        logger.warning("写入幂等失败状态失败 scope=%s key=%s", scope, key,
                       exc_info=True)


def reset(scope: str, key: str) -> None:
    """删除一条记录（测试与运维用）。"""
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM idempotency_key WHERE scope = :scope AND key = :key"),
            {"scope": scope, "key": key})
        session.commit()
