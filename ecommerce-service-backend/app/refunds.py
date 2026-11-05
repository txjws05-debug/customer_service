"""退款记账：取消订单与售后完成共用同一本账。"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app import shop_rules as rules
from app.shop_service import ShopError


def paid_payment(db: Session, order: models.Order) -> models.Payment | None:
    """这笔订单的成功支付（含已部分退款）。加行锁：并发退款不能把余额算重。"""
    return db.scalar(
        select(models.Payment)
        .filter(models.Payment.order_id == order.id,
                models.Payment.status.in_(("success", "refunded")))
        .order_by(models.Payment.id.desc())
        .with_for_update())


def refunded_total(db: Session, payment: models.Payment) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(models.Refund.amount), 0))
                      .filter(models.Refund.payment_id == payment.id))
    return Decimal(total)


def record_refund(db: Session, order: models.Order, amount: Decimal, *,
                  source: str, reason: str, ticket_no: str | None = None) -> Decimal:
    """记一笔退款并返回金额；订单没付过款返回 0。不 commit，跟调用方同一事务。

    累计退款不能超过实付：超过说明上游状态机有漏洞（比如退完款又取消），
    宁可拒绝也不能多退。
    """
    payment = paid_payment(db, order)
    amount = rules.money(amount)
    if payment is None or amount <= 0:
        return Decimal("0")
    already = refunded_total(db, payment)
    if already + amount > payment.amount:
        raise ShopError(
            f"退款金额超过实付：已退 {already}，本次 {amount}，实付 {payment.amount}。", 409)
    now = rules.now()
    db.add(models.Refund(
        refund_no=f"RF{now:%Y%m%d%H%M%S}{order.id:06d}{uuid.uuid4().hex[:4].upper()}",
        order_id=order.id, payment_id=payment.id, amount=amount, source=source,
        ticket_no=ticket_no, reason=reason[:255], created_at=now))
    if already + amount == payment.amount:
        payment.status = "refunded"
    return amount
