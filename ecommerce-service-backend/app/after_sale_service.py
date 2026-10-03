"""售后工单与评价的业务逻辑。

售后状态机（与 shop_rules.AFTER_SALE_TRANSITIONS 一致）：
    submitted --审核通过--> approved --寄回--> returning --商家验收--> received --> completed
        |                        |
        +--审核驳回--> rejected   +--仅退款可直接 completed
    submitted/approved 可撤销 --> canceled

评价规则：
- 只有「已完成」的订单能评价，且必须评价订单里真实存在的商品；
- 同一订单同一商品只能评一次（依赖 reviews 表的唯一约束）；
- 评价后立即刷新商品的评分聚合；
- 评价成功赠积分（走积分流水，保证与余额一致）。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app import shop_rules as rules
from app.shop_schemas import (
    AfterSaleCreateRequest,
    AfterSaleListData,
    AfterSaleTicketData,
    ReviewCreateRequest,
    ReviewData,
    ReviewListData,
)
from app.shop_service import ShopError, get_user


# ============================================================ 售后工单
def _ticket_query(db: Session):
    return db.query(models.AfterSaleTicket).options(
        joinedload(models.AfterSaleTicket.order))


def _ticket_to_data(ticket: models.AfterSaleTicket) -> AfterSaleTicketData:
    return AfterSaleTicketData(
        ticket_no=ticket.ticket_no, order_id=ticket.order.order_id,
        type=ticket.type, type_desc=rules.AFTER_SALE_TYPE_DESC.get(ticket.type, ticket.type),
        status=ticket.status, status_desc=rules.describe_after_sale(ticket.status),
        reason=ticket.reason, evidence=ticket.evidence_json or [],
        refund_amount=ticket.refund_amount, remark=ticket.remark,
        created_at=ticket.created_at, updated_at=ticket.updated_at,
        can_cancel=ticket.status in {rules.AS_SUBMITTED, rules.AS_APPROVED},
        can_return=(ticket.type == "return_refund" and ticket.status == rules.AS_APPROVED),
    )


def _get_ticket(db: Session, ticket_no: str) -> models.AfterSaleTicket:
    ticket = _ticket_query(db).filter(models.AfterSaleTicket.ticket_no == ticket_no).first()
    if not ticket:
        raise ShopError(f"售后单 {ticket_no} 不存在。", 404)
    return ticket


def create_after_sale(
    db: Session, user: models.User, order_id: str, payload: AfterSaleCreateRequest,
) -> AfterSaleTicketData:
    order = db.scalar(
        select(models.Order)
        .options(joinedload(models.Order.items))
        .filter(models.Order.order_id == order_id, models.Order.user_id == user.id)
    )
    if not order:
        raise ShopError(f"订单 {order_id} 不存在或不属于当前用户。", 404)
    if order.status not in rules.AFTER_SALE_ALLOWED_STATUS:
        raise ShopError(f"订单当前状态为「{order.status}」，暂不支持申请售后。", 409)
    if payload.type not in rules.AFTER_SALE_TYPE_DESC:
        raise ShopError(f"不支持的售后类型：{payload.type}", 400)

    open_ticket = db.scalar(
        select(models.AfterSaleTicket)
        .filter(models.AfterSaleTicket.order_id == order.id)
        .filter(models.AfterSaleTicket.status.in_(
            [rules.AS_SUBMITTED, rules.AS_APPROVED, rules.AS_RETURNING, rules.AS_RECEIVED]))
    )
    if open_ticket:
        raise ShopError(f"该订单已有进行中的售后单 {open_ticket.ticket_no}。", 409)

    payable = order.payable
    refund_amount = payload.refund_amount if payload.refund_amount is not None else payable
    if refund_amount <= 0:
        raise ShopError("退款金额必须大于 0。", 400)
    if refund_amount > payable:
        raise ShopError(f"退款金额不能超过实付金额 {payable} 元。", 400)

    now = rules.now()
    ticket = models.AfterSaleTicket(
        ticket_no=rules.new_ticket_no(), order_id=order.id, user_id=user.id,
        type=payload.type, status=rules.AS_SUBMITTED, reason=payload.reason,
        evidence_json=list(payload.evidence), refund_amount=rules.money(refund_amount),
        created_at=now, updated_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


def list_after_sales(
    db: Session, user: models.User, status: str | None = None,
) -> AfterSaleListData:
    query = _ticket_query(db).filter(models.AfterSaleTicket.user_id == user.id)
    if status:
        query = query.filter(models.AfterSaleTicket.status == status)
    tickets = query.order_by(models.AfterSaleTicket.id.desc()).all()
    return AfterSaleListData(
        user_id=user.user_id, total=len(tickets),
        tickets=[_ticket_to_data(t) for t in tickets],
    )


def after_sale_detail(db: Session, ticket_no: str) -> AfterSaleTicketData:
    return _ticket_to_data(_get_ticket(db, ticket_no))


def cancel_after_sale(db: Session, ticket_no: str) -> AfterSaleTicketData:
    ticket = _get_ticket(db, ticket_no)
    if not rules.can_transition_after_sale(ticket.status, rules.AS_CANCELED):
        raise ShopError(f"售后单当前状态为「{ticket.status}」，无法撤销。", 409)
    ticket.status = rules.AS_CANCELED
    ticket.updated_at = rules.now()
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


def submit_return(
    db: Session, ticket_no: str, tracking_number: str, company: str,
) -> AfterSaleTicketData:
    ticket = _get_ticket(db, ticket_no)
    if ticket.type != "return_refund":
        raise ShopError("仅退款类型无需寄回商品。", 409)
    if not rules.can_transition_after_sale(ticket.status, rules.AS_RETURNING):
        raise ShopError(f"售后单当前状态为「{ticket.status}」，无法提交寄回信息。", 409)
    ticket.status = rules.AS_RETURNING
    ticket.remark = f"{company} {tracking_number}"
    ticket.updated_at = rules.now()
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


# ---- 运营端动作（供管理端路由与后续切片复用）----
def review_ticket(
    db: Session, ticket_no: str, approved: bool, remark: str | None = None,
) -> AfterSaleTicketData:
    """审核：通过后进入 approved（退货退款需再寄回；仅退款可直接完成）。"""
    ticket = _get_ticket(db, ticket_no)
    target = rules.AS_APPROVED if approved else rules.AS_REJECTED
    if not rules.can_transition_after_sale(ticket.status, target):
        raise ShopError(f"售后单当前状态为「{ticket.status}」，无法审核。", 409)
    ticket.status = target
    if remark:
        ticket.remark = remark
    ticket.updated_at = rules.now()
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


def receive_return(db: Session, ticket_no: str, remark: str | None = None) -> AfterSaleTicketData:
    """商家收到退回商品：returning → received。"""
    ticket = _get_ticket(db, ticket_no)
    if not rules.can_transition_after_sale(ticket.status, rules.AS_RECEIVED):
        raise ShopError(f"售后单当前状态为「{ticket.status}」，无法确认收货。", 409)
    ticket.status = rules.AS_RECEIVED
    if remark:
        ticket.remark = remark
    ticket.updated_at = rules.now()
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


def complete_after_sale(
    db: Session, ticket_no: str, remark: str | None = None,
) -> AfterSaleTicketData:
    """完成售后：退款并（退货退款时）把库存还回去。"""
    ticket = _get_ticket(db, ticket_no)
    if not rules.can_transition_after_sale(ticket.status, rules.AS_COMPLETED):
        raise ShopError(f"售后单当前状态为「{ticket.status}」，无法完成。", 409)

    # 退货验收通过后库存回滚（仅退款不涉及库存）
    if ticket.type == "return_refund":
        order = ticket.order
        for item in order.items:
            if not item.sku_id:
                continue
            sku = db.scalar(
                select(models.ProductSku)
                .filter(models.ProductSku.id == item.sku_id)
                .with_for_update()
            )
            if sku:
                sku.stock += item.quantity
                db.add(models.InventoryLog(
                    sku_id=sku.id, change=item.quantity, stock_after=sku.stock,
                    reason="after_sale_return", order_id=order.id, created_at=rules.now(),
                ))

    ticket.status = rules.AS_COMPLETED
    if remark:
        ticket.remark = remark
    ticket.updated_at = rules.now()
    db.commit()
    db.refresh(ticket)
    return _ticket_to_data(ticket)


def list_all_tickets(
    db: Session, status: str | None = None, limit: int = 50,
) -> AfterSaleListData:
    query = _ticket_query(db)
    if status:
        query = query.filter(models.AfterSaleTicket.status == status)
    tickets = query.order_by(models.AfterSaleTicket.id.desc()).limit(limit).all()
    return AfterSaleListData(
        user_id="*", total=len(tickets), tickets=[_ticket_to_data(t) for t in tickets])


# ============================================================ 评价
def _refresh_product_rating(db: Session, product: models.Product) -> None:
    avg, count = db.execute(
        select(func.avg(models.Review.rating), func.count(models.Review.id))
        .filter(models.Review.product_id == product.id)
    ).one()
    product.rating_avg = Decimal(str(round(float(avg), 2))) if avg is not None else Decimal("0")
    product.rating_count = int(count or 0)


def _review_to_data(review: models.Review) -> ReviewData:
    return ReviewData(
        id=review.id, order_id=review.order.order_id if review.order else "",
        product_id=review.product.product_id if review.product else "",
        rating=review.rating, content=review.content, images=review.images_json or [],
        reply=review.reply, append_content=review.append_content,
        nickname=review.user.nickname if review.user else "匿名用户",
        created_at=review.created_at,
    )


def create_reviews(
    db: Session, user: models.User, order_id: str, payload: ReviewCreateRequest,
) -> list[ReviewData]:
    order = db.scalar(
        select(models.Order)
        .options(joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .filter(models.Order.order_id == order_id, models.Order.user_id == user.id)
    )
    if not order:
        raise ShopError(f"订单 {order_id} 不存在或不属于当前用户。", 404)
    if order.status != rules.STATUS_FINISHED:
        raise ShopError(f"订单状态为「{order.status}」，只有已完成的订单可以评价。", 409)

    product_ids = {item.product.product_id for item in order.items if item.product}
    existing = {
        review.product_id
        for review in db.scalars(
            select(models.Review).filter(models.Review.order_id == order.id)).all()
    }
    created: list[models.Review] = []
    now = rules.now()
    for entry in payload.items:
        if entry.product_id not in product_ids:
            raise ShopError(f"商品 {entry.product_id} 不在订单 {order_id} 中。", 400)
        product = next(
            item.product for item in order.items
            if item.product and item.product.product_id == entry.product_id)
        if product.id in existing:
            raise ShopError(f"商品 {entry.product_id} 已经评价过了。", 409)
        review = models.Review(
            order_id=order.id, product_id=product.id, user_id=user.id,
            rating=entry.rating, content=entry.content,
            images_json=list(entry.images), created_at=now,
        )
        db.add(review)
        created.append(review)
        existing.add(product.id)

    db.flush()
    for review in created:
        if review.product:
            _refresh_product_rating(db, review.product)

    # 评价赠积分，保证与积分流水一致
    if created:
        earned = rules.POINTS_PER_REVIEW * len(created)
        user.points = (user.points or 0) + earned
        db.add(models.PointsLedger(
            user_id=user.id, change=earned, balance_after=user.points,
            reason="评价奖励", order_id=order.id, created_at=now,
        ))

    db.commit()
    for review in created:
        db.refresh(review)
    return [_review_to_data(r) for r in created]


def list_product_reviews(
    db: Session, product_id: str, page: int = 1, page_size: int = 10,
) -> ReviewListData:
    product = db.scalar(
        select(models.Product).filter(models.Product.product_id == product_id))
    if not product:
        raise ShopError(f"商品 {product_id} 不存在。", 404)
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    base = db.query(models.Review).filter(models.Review.product_id == product.id)
    total = base.count()
    reviews = (
        base.options(
            joinedload(models.Review.user), joinedload(models.Review.product),
            joinedload(models.Review.order))
        .order_by(models.Review.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ReviewListData(
        product_id=product.product_id, total=total,
        rating_avg=product.rating_avg or Decimal("0"),
        rating_count=product.rating_count or 0,
        reviews=[_review_to_data(r) for r in reviews],
    )


def _get_review(db: Session, review_id: int) -> models.Review:
    review = db.scalar(
        select(models.Review)
        .options(joinedload(models.Review.user), joinedload(models.Review.product),
                 joinedload(models.Review.order))
        .filter(models.Review.id == review_id)
    )
    if not review:
        raise ShopError(f"评价 {review_id} 不存在。", 404)
    return review


def append_review(db: Session, user: models.User, review_id: int, content: str) -> ReviewData:
    review = _get_review(db, review_id)
    if review.user_id != user.id:
        raise ShopError("只能追加自己的评价。", 403)
    if review.append_content:
        raise ShopError("该评价已经追评过了。", 409)
    review.append_content = content
    db.commit()
    db.refresh(review)
    return _review_to_data(review)


def reply_review(db: Session, review_id: int, reply: str) -> ReviewData:
    """商家回复（运营端）。"""
    review = _get_review(db, review_id)
    review.reply = reply
    db.commit()
    db.refresh(review)
    return _review_to_data(review)


def un_reviewed_orders(db: Session, user: models.User) -> list[str]:
    """已完成的、还有商品没评价的订单号（前端「待评价」入口用）。"""
    orders = db.scalars(
        select(models.Order)
        .options(joinedload(models.Order.items))
        .filter(models.Order.user_id == user.id,
                models.Order.status == rules.STATUS_FINISHED)
        # items 是集合关系，joinedload + all() 必须显式去重
    ).unique().all()
    result = []
    for order in orders:
        reviewed = {
            r.product_id for r in db.scalars(
                select(models.Review).filter(models.Review.order_id == order.id)).all()
        }
        if any(item.product_id not in reviewed for item in order.items):
            result.append(order.order_id)
    return result
