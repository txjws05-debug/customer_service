"""运营端（管理后台）的业务逻辑：发货履约、库存调整、优惠券管理、经营看板。

放在独立模块的原因：这些是「商家视角」的操作，与用户侧的 shop_service 关注点
不同（用户侧关心自己的订单能不能操作，运营端关心全站订单与履约）。
两者共用同一套状态机（shop_rules），所以不会出现两套规则打架。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app import shop_rules as rules
from app.shop_schemas import (
    AdminOrderListData,
    AdminOrderListItem,
    CouponAdminData,
    CouponCreateRequest,
    CouponGrantData,
    FulfillmentData,
    LowStockData,
    StatsData,
    StockData,
    StockUpdateRequest,
    TopProductData,
)
from app.shop_service import ShopError

LOW_STOCK_THRESHOLD = 10


# ============================================================ 订单与履约
def list_orders(
    db: Session, status: str | None = None, user_id: str | None = None,
    page: int = 1, page_size: int = 20,
) -> AdminOrderListData:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    query = db.query(models.Order).options(
        joinedload(models.Order.user),
        joinedload(models.Order.items).joinedload(models.OrderItem.product),
        joinedload(models.Order.logistics_records),
    )
    if status:
        query = query.filter(models.Order.status == status)
    if user_id:
        query = query.filter(models.Order.user.has(user_id=user_id))

    total = query.count()
    orders = (
        query.order_by(models.Order.created_at.desc(), models.Order.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    status_counts = dict(
        db.execute(
            select(models.Order.status, func.count(models.Order.id))
            .group_by(models.Order.status)
        ).all()
    )
    items = []
    for order in orders:
        first = order.items[0] if order.items else None
        logistics = order.logistics_records[-1] if order.logistics_records else None
        items.append(AdminOrderListItem(
            order_id=order.order_id,
            user_id=order.user.user_id if order.user else "",
            nickname=order.user.nickname if order.user else "",
            status=order.status, status_desc=order.status_desc,
            pay_amount=order.payable,
            quantity=sum(i.quantity for i in order.items),
            title=first.title_snapshot if first else "未知商品",
            created_at=order.created_at, paid_at=order.paid_at,
            logistics_company=logistics.logistics_company if logistics else None,
            tracking_number=logistics.tracking_number if logistics else None,
        ))
    return AdminOrderListData(
        total=total, page=page, page_size=page_size,
        status_counts={k: int(v) for k, v in status_counts.items()},
        orders=items,
    )


def _get_order(db: Session, order_id: str) -> models.Order:
    order = db.scalar(
        select(models.Order)
        .options(joinedload(models.Order.logistics_records))
        .filter(models.Order.order_id == order_id)
    )
    if not order:
        raise ShopError(f"订单 {order_id} 不存在。", 404)
    return order


def _append_trace(db: Session, order: models.Order, text: str,
                  company: str | None = None, tracking: str | None = None) -> models.LogisticsRecord:
    record = order.logistics_records[-1] if order.logistics_records else None
    if record is None:
        record = models.LogisticsRecord(
            order_id=order.id, logistics_company=company or "顺丰速运",
            tracking_number=tracking or f"SF{order.id:010d}",
            status="已出库", status_desc=text, updated_at=rules.now(),
        )
        db.add(record)
        db.flush()
        order.logistics_records.append(record)
    record.status_desc = text
    record.updated_at = rules.now()
    db.add(models.LogisticsTrace(
        logistics_record_id=record.id, trace_time=rules.now(), trace_desc=text))
    return record


def _fulfillment(order: models.Order) -> FulfillmentData:
    record = order.logistics_records[-1] if order.logistics_records else None
    latest = None
    if record and record.traces:
        latest = record.traces[-1].trace_desc
    return FulfillmentData(
        order_id=order.order_id, status=order.status, status_desc=order.status_desc,
        logistics_company=record.logistics_company if record else None,
        tracking_number=record.tracking_number if record else None,
        latest_trace=latest,
    )


def ship_order(
    db: Session, order_id: str, company: str, tracking_number: str | None = None,
) -> FulfillmentData:
    """发货：待发货 → 待揽收，并建立物流单。"""
    order = _get_order(db, order_id)
    if not rules.can_transition(order.status, rules.STATUS_PENDING_PICKUP):
        raise ShopError(f"订单当前状态为「{order.status}」，无法发货。", 409)

    record = _append_trace(
        db, order, "商家已出库，等待快递揽收。", company=company,
        tracking=tracking_number)
    record.logistics_company = company
    if tracking_number:
        record.tracking_number = tracking_number

    from_status = order.status
    order.status = rules.STATUS_PENDING_PICKUP
    order.status_desc = rules.describe(rules.STATUS_PENDING_PICKUP)
    order.shipped_at = rules.now()
    db.add(models.OrderStatusLog(
        order_id=order.id, from_status=from_status, to_status=order.status,
        operator="admin", remark=f"{company} {record.tracking_number}",
        created_at=rules.now(),
    ))
    db.commit()
    db.refresh(order)
    return _fulfillment(order)


ADVANCE_STEPS = {
    rules.STATUS_PENDING_PICKUP: (
        rules.STATUS_IN_TRANSIT, "快递已揽收，包裹运输中。"),
    rules.STATUS_IN_TRANSIT: (
        rules.STATUS_PENDING_RECEIVE, "包裹已到达派送点，正在派送。"),
}


def advance_order(db: Session, order_id: str, remark: str | None = None) -> FulfillmentData:
    """推进履约：待揽收 → 运输中 → 待收货（每次附一条物流轨迹）。"""
    order = _get_order(db, order_id)
    step = ADVANCE_STEPS.get(order.status)
    if not step:
        raise ShopError(
            f"订单当前状态为「{order.status}」，无需推进履约（待揽收/运输中才可推进）。", 409)
    target, text = step
    if not rules.can_transition(order.status, target):
        raise ShopError(f"订单当前状态为「{order.status}」，无法推进。", 409)

    _append_trace(db, order, remark or text)
    from_status = order.status
    order.status = target
    order.status_desc = rules.describe(target)
    db.add(models.OrderStatusLog(
        order_id=order.id, from_status=from_status, to_status=target,
        operator="admin", remark=remark or text, created_at=rules.now(),
    ))
    db.commit()
    db.refresh(order)
    return _fulfillment(order)


# ============================================================ 库存
def update_stock(
    db: Session, sku_code: str, payload: StockUpdateRequest,
) -> StockData:
    # 加行锁时不要 joinedload：joinedload 会变成 LEFT OUTER JOIN，
    # 而 PostgreSQL 不允许对 outer join 的可空侧加 FOR UPDATE
    # （会报 FOR UPDATE cannot be applied to the nullable side of an outer join）
    sku = db.scalar(
        select(models.ProductSku)
        .filter(models.ProductSku.sku_code == sku_code)
        .with_for_update()
    )
    if not sku:
        raise ShopError(f"商品规格 {sku_code} 不存在。", 404)
    product = sku.product
    change = payload.stock - sku.stock
    if change == 0:
        raise ShopError("库存没有变化。", 400)
    sku.stock = payload.stock
    db.add(models.InventoryLog(
        sku_id=sku.id, change=change, stock_after=sku.stock,
        reason=payload.reason, order_id=None, created_at=rules.now(),
    ))
    db.commit()
    db.refresh(sku)
    return StockData(
        sku_code=sku.sku_code, product_id=product.product_id if product else "",
        title=product.title if product else "", spec_text=sku.spec_text,
        stock=sku.stock, change=change, status=sku.status,
    )


def low_stock(db: Session, threshold: int = LOW_STOCK_THRESHOLD) -> list[LowStockData]:
    skus = db.scalars(
        select(models.ProductSku)
        .options(joinedload(models.ProductSku.product))
        .filter(models.ProductSku.stock <= threshold)
        .order_by(models.ProductSku.stock)
    ).all()
    return [
        LowStockData(
            sku_code=sku.sku_code,
            product_id=sku.product.product_id if sku.product else "",
            title=sku.product.title if sku.product else "",
            spec_text=sku.spec_text, stock=sku.stock,
        )
        for sku in skus
    ]


# ============================================================ 优惠券
def _coupon_to_admin(db: Session, coupon: models.Coupon) -> CouponAdminData:
    used = db.scalar(
        select(func.count(models.UserCoupon.id))
        .filter(models.UserCoupon.coupon_id == coupon.id)
        .filter(models.UserCoupon.status == "used")
    )
    return CouponAdminData(
        code=coupon.code, name=coupon.name, type=coupon.type,
        threshold=coupon.threshold, amount=coupon.amount, rate=coupon.rate,
        start_at=coupon.start_at, end_at=coupon.end_at,
        total=coupon.total, claimed=coupon.claimed,
        used_count=int(used or 0), per_user_limit=coupon.per_user_limit,
    )


def list_coupons(db: Session) -> list[CouponAdminData]:
    coupons = db.scalars(select(models.Coupon).order_by(models.Coupon.id.desc())).all()
    return [_coupon_to_admin(db, c) for c in coupons]


def create_coupon(db: Session, payload: CouponCreateRequest) -> CouponAdminData:
    if payload.type not in {"full_reduce", "discount"}:
        raise ShopError("券类型只支持 full_reduce（满减）或 discount（折扣）。", 400)
    if payload.type == "full_reduce" and payload.amount is None:
        raise ShopError("满减券必须给 amount。", 400)
    if payload.type == "discount" and payload.rate is None:
        raise ShopError("折扣券必须给 rate（如 0.9 表示 9 折）。", 400)
    if db.scalar(select(models.Coupon).filter(models.Coupon.code == payload.code)):
        raise ShopError(f"券码 {payload.code} 已存在。", 409)

    now = rules.now()
    coupon = models.Coupon(
        code=payload.code, name=payload.name, type=payload.type,
        threshold=payload.threshold, amount=payload.amount, rate=payload.rate,
        start_at=now, end_at=now + timedelta(days=payload.days),
        total=payload.total, claimed=0, per_user_limit=payload.per_user_limit,
        created_at=now,
    )
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    return _coupon_to_admin(db, coupon)


def grant_coupon(db: Session, code: str, user_ids: list[str]) -> CouponGrantData:
    """定向发券。超出每人限领或用户不存在的会进 skipped，而不是整批失败。"""
    coupon = db.scalar(select(models.Coupon).filter(models.Coupon.code == code))
    if not coupon:
        raise ShopError(f"券码 {code} 不存在。", 404)

    granted = 0
    skipped: list[str] = []
    for biz_id in user_ids:
        user = db.scalar(select(models.User).filter(models.User.user_id == biz_id))
        if not user:
            skipped.append(biz_id)
            continue
        owned = db.scalar(
            select(func.count(models.UserCoupon.id))
            .filter(models.UserCoupon.user_id == user.id)
            .filter(models.UserCoupon.coupon_id == coupon.id)
        )
        if int(owned or 0) >= coupon.per_user_limit:
            skipped.append(biz_id)
            continue
        if coupon.total and coupon.claimed >= coupon.total:
            skipped.append(biz_id)
            continue
        db.add(models.UserCoupon(
            user_id=user.id, coupon_id=coupon.id, status="unused",
            received_at=rules.now(),
        ))
        coupon.claimed += 1
        granted += 1
    db.commit()
    return CouponGrantData(code=code, granted=granted, skipped=skipped)


# ============================================================ 看板
def stats(db: Session) -> StatsData:
    paid_filter = (models.Order.paid_at.isnot(None),
                   models.Order.status != rules.STATUS_CANCELED)
    gmv = db.scalar(
        select(func.coalesce(func.sum(models.Order.pay_amount), 0)).filter(*paid_filter))
    paid_count = db.scalar(
        select(func.count(models.Order.id)).filter(*paid_filter)) or 0
    finished_count = db.scalar(
        select(func.count(models.Order.id))
        .filter(models.Order.status == rules.STATUS_FINISHED)) or 0
    canceled_count = db.scalar(
        select(func.count(models.Order.id))
        .filter(models.Order.status == rules.STATUS_CANCELED)) or 0
    status_counts = {
        k: int(v) for k, v in db.execute(
            select(models.Order.status, func.count(models.Order.id))
            .group_by(models.Order.status)
        ).all()
    }

    after_sale_count = db.scalar(select(func.count(models.AfterSaleTicket.id))) or 0
    rate = Decimal("0")
    if paid_count:
        rate = rules.money(Decimal(after_sale_count) * 100 / Decimal(paid_count))

    coupon_issued = db.scalar(
        select(func.coalesce(func.sum(models.Coupon.claimed), 0))) or 0
    coupon_used = db.scalar(
        select(func.count(models.UserCoupon.id))
        .filter(models.UserCoupon.status == "used")) or 0
    points_issued = db.scalar(
        select(func.coalesce(func.sum(models.PointsLedger.change), 0))
        .filter(models.PointsLedger.change > 0)) or 0

    top_rows = db.execute(
        select(
            models.Product.product_id, models.Product.title,
            func.coalesce(func.sum(models.OrderItem.quantity), 0).label("qty"),
            func.coalesce(func.sum(models.OrderItem.price * models.OrderItem.quantity), 0)
            .label("amount"),
        )
        .join(models.OrderItem, models.OrderItem.product_id == models.Product.id)
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .filter(models.Order.status != rules.STATUS_CANCELED)
        .group_by(models.Product.product_id, models.Product.title)
        .order_by(func.coalesce(func.sum(models.OrderItem.quantity), 0).desc())
        .limit(5)
    ).all()

    return StatsData(
        gmv=rules.money(gmv or 0),
        paid_order_count=int(paid_count),
        finished_order_count=int(finished_count),
        canceled_order_count=int(canceled_count),
        status_counts=status_counts,
        after_sale_count=int(after_sale_count),
        after_sale_rate=rate,
        coupon_issued=int(coupon_issued),
        coupon_used=int(coupon_used),
        points_issued=int(points_issued),
        user_count=int(db.scalar(select(func.count(models.User.id))) or 0),
        product_count=int(db.scalar(
            select(func.count(models.Product.id))
            .filter(models.Product.status == "在售")) or 0),
        low_stock=low_stock(db),
        top_products=[
            TopProductData(
                product_id=row.product_id, title=row.title,
                quantity=int(row.qty), amount=rules.money(row.amount),
            )
            for row in top_rows
        ],
    )
