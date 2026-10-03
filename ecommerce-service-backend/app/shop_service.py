"""交易域的业务逻辑（购物车、结算、下单、支付、发货收货、取消）。

路由层只做参数校验与错误映射，真正的规则都在这里，因此可以脱离 HTTP 单测。

几条必须守住的不变量：
1. 扣库存一律 `SELECT ... FOR UPDATE`（行锁），避免并发下超卖；
2. 金额只由 shop_rules 计算，且 `pay_amount = goods - discount + freight`；
3. 状态流转只走 shop_rules 的状态机，非法流转直接报错；
4. 每一次库存变动都写 inventory_logs，每一次状态变化都写 order_status_logs；
5. 优惠券：下单占用（status=used + order_id），取消时归还。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app import shop_rules as rules
from app.shop_schemas import (
    AddressCreateRequest,
    AddressData,
    AddressListData,
    AmountPreviewData,
    CartData,
    CartLineData,
    CategoryData,
    CouponInfo,
    OrderActionResult,
    OrderCreatedData,
    OrderItemData,
    OrderListItem,
    OrderListData,
    OrderStatusLogData,
    PayData,
    PointsData,
    PointsLogData,
    ProductDetailData,
    ProductListData,
    ProductListItem,
    ShopOrderDetailData,
    SkuData,
    UserCouponData,
    UserCouponListData,
)


class ShopError(Exception):
    """业务校验失败。status_code 供路由层映射成 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ============================================================ 通用查询
def get_user(db: Session, user_id: str) -> models.User:
    user = db.scalar(select(models.User).filter(models.User.user_id == user_id))
    if not user:
        raise ShopError(f"用户 {user_id} 不存在。", 404)
    return user


def get_sku_by_code(db: Session, sku_code: str) -> models.ProductSku:
    sku = db.scalar(
        select(models.ProductSku)
        .options(joinedload(models.ProductSku.product))
        .filter(models.ProductSku.sku_code == sku_code)
    )
    if not sku:
        raise ShopError(f"商品规格 {sku_code} 不存在。", 404)
    return sku


def sku_to_data(sku: models.ProductSku) -> SkuData:
    return SkuData(
        sku_id=sku.id, sku_code=sku.sku_code, spec=sku.spec_json or {},
        spec_text=sku.spec_text, price=sku.price, original_price=sku.original_price,
        stock=sku.stock, status=sku.status,
    )


# ============================================================ 商品与搜索
def list_categories(db: Session) -> list[CategoryData]:
    categories = db.scalars(select(models.Category).order_by(models.Category.sort)).all()
    result = []
    for category in categories:
        total = db.query(models.Product).filter(
            models.Product.category_id == category.id,
            models.Product.status == "在售",
        ).count()
        result.append(CategoryData(id=category.id, name=category.name, product_count=total))
    return result


SORT_CHOICES = {
    "default": (models.Product.sales_count.desc(), models.Product.id.asc()),
    "sales": (models.Product.sales_count.desc(), models.Product.id.asc()),
    "rating": (models.Product.rating_avg.desc(), models.Product.sales_count.desc()),
    "price_asc": (models.Product.price.asc(), models.Product.id.asc()),
    "price_desc": (models.Product.price.desc(), models.Product.id.asc()),
    "newest": (models.Product.created_at.desc(), models.Product.id.desc()),
}


def search_products(
    db: Session,
    keyword: str | None = None,
    category_id: int | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = "default",
    page: int = 1,
    page_size: int = 10,
) -> ProductListData:
    """商品搜索：关键词 + 类目 + 价格区间 + 排序 + 分页。

    关键词用 ILIKE 同时匹配标题与属性（小型版不引入全文检索；
    pg_trgm 可作为后续增强，接口形状不变）。
    """
    if sort not in SORT_CHOICES:
        raise ShopError(f"不支持的排序方式：{sort}", 400)
    page = max(1, page)
    page_size = min(max(1, page_size), 50)

    query = db.query(models.Product).filter(models.Product.status == "在售")
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            models.Product.title.ilike(like) | models.Product.description.ilike(like))
    if category_id:
        query = query.filter(models.Product.category_id == category_id)
    if min_price is not None:
        query = query.filter(models.Product.price >= min_price)
    if max_price is not None:
        query = query.filter(models.Product.price <= max_price)

    total = query.count()
    products = (
        query.options(joinedload(models.Product.category))
        .order_by(*SORT_CHOICES[sort])
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ProductListData(
        total=total, page=page, page_size=page_size, keyword=keyword,
        items=[_product_list_item(p) for p in products],
    )


def _product_list_item(product: models.Product) -> ProductListItem:
    return ProductListItem(
        product_id=product.product_id, title=product.title, price=product.price,
        cover_url=product.cover_url,
        category=product.category.name if product.category else None,
        brand=product.brand, stock_status=product.stock_status,
        rating_avg=product.rating_avg or Decimal("0"),
        rating_count=product.rating_count or 0,
        sales_count=product.sales_count or 0,
    )


def product_detail(db: Session, product_id: str) -> ProductDetailData:
    product = db.scalar(
        select(models.Product)
        .options(joinedload(models.Product.category), joinedload(models.Product.skus))
        .filter(models.Product.product_id == product_id)
    )
    if not product:
        raise ShopError(f"商品 {product_id} 不存在。", 404)
    skus = [s for s in product.skus if s.status == "在售"]
    skus.sort(key=lambda s: s.id)
    return ProductDetailData(
        product_id=product.product_id, title=product.title,
        description=product.description, cover_url=product.cover_url,
        category=product.category.name if product.category else None,
        brand=product.brand, status=product.status,
        rating_avg=product.rating_avg or Decimal("0"),
        rating_count=product.rating_count or 0,
        sales_count=product.sales_count or 0,
        attributes=product.attributes_json or {},
        skus=[sku_to_data(s) for s in skus],
    )


# ============================================================ 购物车
def _cart_query(db: Session, user: models.User):
    return (
        db.query(models.CartItem)
        .options(
            joinedload(models.CartItem.sku).joinedload(models.ProductSku.product)
        )
        .filter(models.CartItem.user_id == user.id)
        .order_by(models.CartItem.id)
    )


def cart_to_data(db: Session, user: models.User) -> CartData:
    items = _cart_query(db, user).all()
    lines: list[CartLineData] = []
    selected_amount = Decimal("0")
    selected_quantity = 0
    for item in items:
        sku = item.sku
        product = sku.product if sku else None
        available = bool(sku) and sku.status == "在售" and sku.stock >= item.quantity
        subtotal = rules.money(sku.price * item.quantity) if sku else Decimal("0")
        lines.append(CartLineData(
            item_id=item.id, sku_id=item.sku_id,
            sku_code=sku.sku_code if sku else "",
            product_id=product.product_id if product else "",
            title=product.title if product else "",
            spec_text=sku.spec_text if sku else "",
            cover_url=product.cover_url if product else None,
            price=sku.price if sku else Decimal("0"),
            quantity=item.quantity, selected=item.selected,
            stock=sku.stock if sku else 0, available=available, subtotal=subtotal,
        ))
        if item.selected:
            selected_amount += subtotal
            selected_quantity += item.quantity
    return CartData(
        user_id=user.user_id, items=lines,
        total_quantity=sum(i.quantity for i in items),
        selected_quantity=selected_quantity,
        selected_amount=rules.money(selected_amount),
    )


def add_to_cart(db: Session, user: models.User, sku_code: str, quantity: int) -> CartData:
    sku = get_sku_by_code(db, sku_code)
    if sku.status != "在售":
        raise ShopError(f"规格 {sku_code} 已下架。")
    if sku.stock <= 0:
        raise ShopError(f"规格 {sku_code} 库存不足。")

    item = db.scalar(
        select(models.CartItem)
        .filter(models.CartItem.user_id == user.id, models.CartItem.sku_id == sku.id)
    )
    now = rules.now()
    new_quantity = quantity + (item.quantity if item else 0)
    if new_quantity > sku.stock:
        raise ShopError(f"库存仅剩 {sku.stock} 件，无法再加购。")
    if item:
        item.quantity = new_quantity
        item.selected = True
        item.updated_at = now
    else:
        db.add(models.CartItem(
            user_id=user.id, sku_id=sku.id, quantity=quantity, selected=True,
            created_at=now, updated_at=now,
        ))
    db.commit()
    return cart_to_data(db, user)


def update_cart_item(
    db: Session, user: models.User, item_id: int,
    quantity: int | None = None, selected: bool | None = None,
) -> CartData:
    item = db.scalar(
        select(models.CartItem)
        .options(joinedload(models.CartItem.sku))
        .filter(models.CartItem.id == item_id, models.CartItem.user_id == user.id)
    )
    if not item:
        raise ShopError(f"购物车条目 {item_id} 不存在。", 404)
    if quantity is not None:
        if item.sku and quantity > item.sku.stock:
            raise ShopError(f"库存仅剩 {item.sku.stock} 件。")
        item.quantity = quantity
    if selected is not None:
        item.selected = selected
    item.updated_at = rules.now()
    db.commit()
    return cart_to_data(db, user)


def remove_cart_item(db: Session, user: models.User, item_id: int) -> CartData:
    item = db.scalar(
        select(models.CartItem)
        .filter(models.CartItem.id == item_id, models.CartItem.user_id == user.id)
    )
    if not item:
        raise ShopError(f"购物车条目 {item_id} 不存在。", 404)
    db.delete(item)
    db.commit()
    return cart_to_data(db, user)


def clear_cart_items(db: Session, user: models.User, item_ids: list[int]) -> None:
    if not item_ids:
        return
    db.query(models.CartItem).filter(
        models.CartItem.user_id == user.id,
        models.CartItem.id.in_(item_ids),
    ).delete(synchronize_session=False)


# ============================================================ 地址
def list_addresses(db: Session, user: models.User) -> AddressListData:
    addresses = db.scalars(
        select(models.Address)
        .filter(models.Address.user_id == user.id)
        .order_by(models.Address.is_default.desc(), models.Address.id)
    ).all()
    return AddressListData(
        user_id=user.user_id,
        addresses=[
            AddressData(id=a.id, receiver_name=a.receiver_name,
                        phone_masked=a.phone_masked, full_address=a.full_address,
                        is_default=a.is_default)
            for a in addresses
        ],
    )


def create_address(db: Session, user: models.User, payload: AddressCreateRequest) -> AddressData:
    if payload.is_default:
        db.query(models.Address).filter(
            models.Address.user_id == user.id).update({"is_default": False})
    address = models.Address(
        user_id=user.id, receiver_name=payload.receiver_name,
        phone_masked=payload.phone_masked, province=payload.province,
        city=payload.city, district=payload.district, detail=payload.detail,
        is_default=payload.is_default, created_at=rules.now(),
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return AddressData(id=address.id, receiver_name=address.receiver_name,
                       phone_masked=address.phone_masked,
                       full_address=address.full_address, is_default=address.is_default)


def _resolve_address(db: Session, user: models.User, address_id: int | None) -> models.Address:
    if address_id is not None:
        address = db.scalar(
            select(models.Address)
            .filter(models.Address.id == address_id, models.Address.user_id == user.id)
        )
        if not address:
            raise ShopError(f"收货地址 {address_id} 不存在。", 404)
        return address
    address = db.scalar(
        select(models.Address)
        .filter(models.Address.user_id == user.id)
        .order_by(models.Address.is_default.desc(), models.Address.id)
    )
    if not address:
        raise ShopError("请先添加收货地址。", 409)
    return address


# ============================================================ 优惠券
def _expire_coupons(db: Session, user: models.User) -> None:
    """把过期的未使用券标记为 expired（读取时顺手做，省掉定时任务）。"""
    now = rules.now()
    db.query(models.UserCoupon).filter(
        models.UserCoupon.user_id == user.id,
        models.UserCoupon.status == "unused",
        models.UserCoupon.coupon_id.in_(
            select(models.Coupon.id).filter(models.Coupon.end_at < now)
        ),
    ).update({"status": "expired"}, synchronize_session=False)


def find_coupon(db: Session, user: models.User, code: str) -> tuple[models.UserCoupon | None, str]:
    """返回 (用户券, 说明)。说明用于预览接口向用户解释为什么没优惠。"""
    _expire_coupons(db, user)
    user_coupon = db.scalar(
        select(models.UserCoupon)
        .options(joinedload(models.UserCoupon.coupon))
        .filter(models.UserCoupon.user_id == user.id)
        .filter(models.UserCoupon.coupon.has(code=code))
        .order_by(models.UserCoupon.id.desc())
    )
    if not user_coupon:
        return None, f"未找到优惠券 {code}（可能未领取）。"
    if user_coupon.status == "used":
        return None, f"优惠券 {code} 已使用。"
    if user_coupon.status == "expired":
        return None, f"优惠券 {code} 已过期。"
    if user_coupon.coupon.end_at < rules.now():
        return None, f"优惠券 {code} 已过期。"
    return user_coupon, ""


def usable_coupons(db: Session, user: models.User, goods_amount: Decimal) -> list[CouponInfo]:
    _expire_coupons(db, user)
    rows = db.scalars(
        select(models.UserCoupon)
        .options(joinedload(models.UserCoupon.coupon))
        .filter(models.UserCoupon.user_id == user.id)
        .filter(models.UserCoupon.status == "unused")
        .order_by(models.UserCoupon.id.desc())
    ).all()
    now = rules.now()
    result = []
    for row in rows:
        coupon = row.coupon
        if coupon.end_at < now or goods_amount < coupon.threshold:
            continue
        result.append(CouponInfo(
            code=coupon.code, name=coupon.name, type=coupon.type,
            threshold=coupon.threshold, amount=coupon.amount, rate=coupon.rate,
            end_at=coupon.end_at,
        ))
    return result


# ============================================================ 结算金额
class _Amounts:
    def __init__(self, goods: Decimal, discount: Decimal, freight: Decimal, pay: Decimal):
        self.goods = goods
        self.discount = discount
        self.freight = freight
        self.pay = pay


def _compute_amounts(
    db: Session, user: models.User, goods_amount: Decimal, coupon_code: str | None,
) -> tuple[_Amounts, models.UserCoupon | None, str]:
    discount = Decimal("0")
    user_coupon = None
    message = ""
    if coupon_code:
        user_coupon, message = find_coupon(db, user, coupon_code)
        if user_coupon:
            coupon = user_coupon.coupon
            discount = rules.compute_coupon_discount(
                coupon.type, goods_amount, coupon.threshold, coupon.amount, coupon.rate)
            if discount <= 0:
                message = f"优惠券 {coupon_code} 未满足使用门槛（满 {coupon.threshold} 元可用）。"
    freight = rules.compute_freight(goods_amount, user.is_plus)
    pay = rules.compute_pay_amount(goods_amount, discount, freight)
    return _Amounts(rules.money(goods_amount), discount, freight, pay), user_coupon, message


def _selected_cart_lines(db: Session, user: models.User):
    items = _cart_query(db, user).filter(models.CartItem.selected.is_(True)).all()
    if not items:
        raise ShopError("购物车中没有已勾选的商品。", 409)
    return items


def preview(
    db: Session, user: models.User, coupon_code: str | None = None,
    address_id: int | None = None,
) -> AmountPreviewData:
    items = _selected_cart_lines(db, user)
    goods_amount = Decimal("0")
    for item in items:
        if not item.sku:
            continue
        if item.sku.status != "在售" or item.sku.stock < item.quantity:
            raise ShopError(f"「{item.sku.product.title if item.sku.product else ''}」库存不足，请调整数量。", 409)
        goods_amount += item.sku.price * item.quantity

    amounts, user_coupon, message = _compute_amounts(db, user, goods_amount, coupon_code)
    address = None
    if address_id is not None:
        address = _resolve_address(db, user, address_id)
    else:
        address = db.scalar(
            select(models.Address).filter(models.Address.user_id == user.id)
            .order_by(models.Address.is_default.desc(), models.Address.id)
        )
    coupon_info = None
    if user_coupon:
        coupon_info = CouponInfo(
            code=user_coupon.coupon.code, name=user_coupon.coupon.name,
            type=user_coupon.coupon.type, threshold=user_coupon.coupon.threshold,
            amount=user_coupon.coupon.amount, rate=user_coupon.coupon.rate,
            end_at=user_coupon.coupon.end_at,
        )
    return AmountPreviewData(
        goods_amount=amounts.goods, discount_amount=amounts.discount,
        freight_amount=amounts.freight, pay_amount=amounts.pay,
        is_plus=user.is_plus,
        free_freight_threshold=rules.FREE_FREIGHT_THRESHOLD,
        coupon=coupon_info, coupon_message=message,
        address_id=address.id if address else None,
        receiver_address=address.full_address if address else None,
    )


# ============================================================ 上下单
def _log_status(db: Session, order: models.Order, from_status: str | None,
                to_status: str, operator: str, remark: str | None = None) -> None:
    db.add(models.OrderStatusLog(
        order_id=order.id, from_status=from_status, to_status=to_status,
        operator=operator, remark=remark, created_at=rules.now(),
    ))


def _change_stock(db: Session, sku: models.ProductSku, change: int,
                  reason: str, order_id: int | None) -> None:
    sku.stock += change
    db.add(models.InventoryLog(
        sku_id=sku.id, change=change, stock_after=sku.stock,
        reason=reason, order_id=order_id, created_at=rules.now(),
    ))


def create_order(
    db: Session,
    user: models.User,
    address_id: int | None = None,
    coupon_code: str | None = None,
    items: list | None = None,
) -> OrderCreatedData:
    """下单：传 items 为立即购买，否则结算购物车中已勾选的商品。"""
    # 超时未支付的旧订单先关掉，避免把库存一直占着
    auto_close_expired_orders(db, user)

    if items:
        lines: list[tuple[models.ProductSku, int]] = []
        for entry in items:
            sku = get_sku_by_code(db, entry.sku_code)
            lines.append((sku, entry.quantity))
        cart_item_ids: list[int] = []
    else:
        cart_items = _selected_cart_lines(db, user)
        lines = [(item.sku, item.quantity) for item in cart_items if item.sku]
        cart_item_ids = [item.id for item in cart_items]

    # 行锁 + 校验库存：并发下单时不会超卖
    sku_ids = [sku.id for sku, _ in lines]
    locked = {
        row.id: row
        for row in db.query(models.ProductSku)
        .filter(models.ProductSku.id.in_(sku_ids))
        .with_for_update()
        .all()
    }
    goods_amount = Decimal("0")
    for sku, quantity in lines:
        current = locked.get(sku.id)
        if current is None or current.status != "在售":
            raise ShopError(f"规格 {sku.sku_code} 已下架。", 409)
        if current.stock < quantity:
            title = current.product.title if current.product else sku.sku_code
            raise ShopError(f"「{title}」库存不足（仅剩 {current.stock} 件）。", 409)
        goods_amount += current.price * quantity

    address = _resolve_address(db, user, address_id)
    amounts, user_coupon, message = _compute_amounts(db, user, goods_amount, coupon_code)
    if coupon_code:
        # 预览接口只解释「为什么没优惠」，但下单必须明确失败——
        # 否则用户以为自己用了券，实际按原价付了款
        if user_coupon is None:
            raise ShopError(message or f"优惠券 {coupon_code} 不可用。", 409)
        if amounts.discount <= 0:
            raise ShopError(message or f"优惠券 {coupon_code} 未满足使用门槛。", 409)

    order = models.Order(
        order_id=rules.new_order_no(), user_id=user.id,
        status=rules.STATUS_PENDING_PAY, status_desc=rules.describe(rules.STATUS_PENDING_PAY),
        amount=amounts.goods, created_at=rules.now(),
        receiver_name=address.receiver_name, receiver_phone_masked=address.phone_masked,
        receiver_address=address.full_address,
        discount_amount=amounts.discount, freight_amount=amounts.freight,
        pay_amount=amounts.pay, address_id=address.id,
    )
    db.add(order)
    db.flush()

    for sku, quantity in lines:
        product = sku.product
        db.add(models.OrderItem(
            order_id=order.id, product_id=product.id,
            title_snapshot=product.title, quantity=quantity, price=sku.price,
            sku_id=sku.id, spec_snapshot=sku.spec_text,
        ))
        _change_stock(db, locked[sku.id], -quantity, "order_created", order.id)

    if user_coupon:
        user_coupon.status = "used"
        user_coupon.order_id = order.id
        user_coupon.used_at = rules.now()

    clear_cart_items(db, user, cart_item_ids)
    _log_status(db, order, None, rules.STATUS_PENDING_PAY, "user", "创建订单")
    db.commit()

    return OrderCreatedData(
        order_id=order.order_id, status=order.status, status_desc=order.status_desc,
        goods_amount=amounts.goods, discount_amount=amounts.discount,
        freight_amount=amounts.freight, pay_amount=amounts.pay,
        coupon_code=coupon_code if user_coupon else None,
        expires_in_minutes=int(rules.AUTO_CLOSE_AFTER.total_seconds() // 60),
    )


# ============================================================ 支付 / 取消 / 收货
def _get_order(db: Session, order_id: str) -> models.Order:
    order = db.scalar(
        select(models.Order)
        .options(
            joinedload(models.Order.items).joinedload(models.OrderItem.product),
            joinedload(models.Order.items).joinedload(models.OrderItem.sku),
            joinedload(models.Order.status_logs),
            joinedload(models.Order.logistics_records),
            joinedload(models.Order.user),
        )
        .filter(models.Order.order_id == order_id)
    )
    if not order:
        raise ShopError(f"订单 {order_id} 不存在。", 404)
    return order


def pay_order(db: Session, order_id: str, channel: str) -> PayData:
    order = _get_order(db, order_id)
    auto_close_expired_orders(db, order.user)
    db.refresh(order)
    if order.status != rules.STATUS_PENDING_PAY:
        raise ShopError(
            f"订单当前状态为「{order.status}」，无法支付。", 409)

    amount = order.payable
    payment = models.Payment(
        order_id=order.id, channel=channel, amount=amount, status="success",
        trade_no=f"PAY{rules.now():%Y%m%d%H%M%S}{order.id:06d}",
        paid_at=rules.now(),
    )
    db.add(payment)
    from_status = order.status
    order.status = rules.STATUS_PENDING_SHIP
    order.status_desc = rules.describe(rules.STATUS_PENDING_SHIP)
    order.paid_at = payment.paid_at
    _log_status(db, order, from_status, order.status, "user", f"{channel} 支付成功")
    db.commit()
    return PayData(
        order_id=order.order_id, trade_no=payment.trade_no, channel=channel,
        amount=amount, status=order.status, status_desc=order.status_desc,
        paid_at=payment.paid_at,
    )


def cancel_order(db: Session, order_id: str, reason: str) -> OrderActionResult:
    order = _get_order(db, order_id)
    if order.status not in rules.CANCELABLE_STATUS:
        raise ShopError(f"订单当前状态为「{order.status}」，无法取消。", 409)

    # 归还库存
    for item in order.items:
        if item.sku_id:
            sku = db.scalar(
                select(models.ProductSku)
                .filter(models.ProductSku.id == item.sku_id)
                .with_for_update()
            )
            if sku:
                _change_stock(db, sku, item.quantity, "order_canceled", order.id)

    # 归还优惠券
    user_coupon = db.scalar(
        select(models.UserCoupon).filter(models.UserCoupon.order_id == order.id))
    if user_coupon and user_coupon.status == "used":
        user_coupon.status = "unused"
        user_coupon.order_id = None
        user_coupon.used_at = None

    from_status = order.status
    order.status = rules.STATUS_CANCELED
    order.status_desc = rules.describe(rules.STATUS_CANCELED)
    order.close_reason = reason
    _log_status(db, order, from_status, order.status, "user", reason)
    db.commit()
    return OrderActionResult(
        order_id=order.order_id, status=order.status, status_desc=order.status_desc,
        pay_amount=order.payable,
    )


def receive_order(db: Session, order_id: str) -> OrderActionResult:
    order = _get_order(db, order_id)
    if not rules.can_transition(order.status, rules.STATUS_FINISHED):
        raise ShopError(f"订单当前状态为「{order.status}」，无法确认收货。", 409)

    user = order.user
    from_status = order.status
    order.status = rules.STATUS_FINISHED
    order.status_desc = rules.describe(rules.STATUS_FINISHED)
    order.received_at = rules.now()
    _log_status(db, order, from_status, order.status, "user", "确认收货")

    earned = rules.calc_points(order.payable, user.is_plus)
    earned_growth = rules.calc_growth(order.payable)
    if earned:
        user.points = (user.points or 0) + earned
        db.add(models.PointsLedger(
            user_id=user.id, change=earned, balance_after=user.points,
            reason="订单完成", order_id=order.id, created_at=rules.now(),
        ))
    if earned_growth:
        user.growth = (user.growth or 0) + earned_growth

    db.commit()
    return OrderActionResult(
        order_id=order.order_id, status=order.status, status_desc=order.status_desc,
        earned_points=earned, pay_amount=order.payable,
    )


def auto_close_expired_orders(db: Session, user: models.User | None = None) -> int:
    """把超时未支付的订单关掉并归还库存/优惠券。

    读取订单时顺手执行，省掉一个定时任务；返回关闭的订单数。
    """
    deadline = rules.now() - rules.AUTO_CLOSE_AFTER
    query = db.query(models.Order).filter(
        models.Order.status == rules.STATUS_PENDING_PAY,
        models.Order.created_at < deadline,
    )
    if user is not None:
        query = query.filter(models.Order.user_id == user.id)
    expired = query.all()
    for order in expired:
        for item in order.items:
            if item.sku_id:
                sku = db.scalar(
                    select(models.ProductSku)
                    .filter(models.ProductSku.id == item.sku_id)
                    .with_for_update()
                )
                if sku:
                    _change_stock(db, sku, item.quantity, "order_auto_closed", order.id)
        user_coupon = db.scalar(
            select(models.UserCoupon).filter(models.UserCoupon.order_id == order.id))
        if user_coupon and user_coupon.status == "used":
            user_coupon.status = "unused"
            user_coupon.order_id = None
            user_coupon.used_at = None
        from_status = order.status
        order.status = rules.STATUS_CANCELED
        order.status_desc = "超时未支付，订单已自动关闭。"
        order.close_reason = "超时未支付"
        _log_status(db, order, from_status, order.status, "system", "超时未支付自动关闭")
    if expired:
        db.commit()
    return len(expired)


# ============================================================ 订单查询
def list_orders(db: Session, user: models.User, status: str | None = None) -> OrderListData:
    auto_close_expired_orders(db, user)
    query = db.query(models.Order).filter(models.Order.user_id == user.id)
    if status:
        query = query.filter(models.Order.status == status)
    orders = (
        query.options(joinedload(models.Order.items).joinedload(models.OrderItem.product))
        .order_by(models.Order.created_at.desc(), models.Order.id.desc())
        .all()
    )
    items = []
    for order in orders:
        first = order.items[0] if order.items else None
        items.append(OrderListItem(
            order_id=order.order_id, status=order.status, status_desc=order.status_desc,
            pay_amount=order.payable,
            quantity=sum(i.quantity for i in order.items),
            title=first.title_snapshot if first else "未知商品",
            cover_url=first.product.cover_url if first and first.product else None,
            created_at=order.created_at,
        ))
    return OrderListData(user_id=user.user_id, total=len(items), orders=items)


def order_detail(db: Session, order_id: str) -> ShopOrderDetailData:
    order = _get_order(db, order_id)
    user = order.user
    auto_close_expired_orders(db, user)
    db.refresh(order)

    logistics = order.logistics_records[-1] if order.logistics_records else None
    items = [
        OrderItemData(
            product_id=item.product.product_id if item.product else "",
            title=item.title_snapshot, spec_text=item.spec_snapshot,
            quantity=item.quantity, price=item.price,
            subtotal=rules.money(item.price * item.quantity),
        )
        for item in order.items
    ]
    logs = [
        OrderStatusLogData(
            from_status=log.from_status, to_status=log.to_status,
            operator=log.operator, remark=log.remark, created_at=log.created_at,
        )
        for log in sorted(order.status_logs, key=lambda x: x.id)
    ]
    return ShopOrderDetailData(
        order_id=order.order_id, status=order.status, status_desc=order.status_desc,
        created_at=order.created_at, paid_at=order.paid_at,
        shipped_at=order.shipped_at, received_at=order.received_at,
        goods_amount=order.amount,
        discount_amount=order.discount_amount or Decimal("0"),
        freight_amount=order.freight_amount or Decimal("0"),
        pay_amount=order.payable, is_plus=bool(user and user.is_plus),
        receiver_name=order.receiver_name,
        receiver_phone_masked=order.receiver_phone_masked,
        receiver_address=order.receiver_address,
        logistics_company=logistics.logistics_company if logistics else None,
        tracking_number=logistics.tracking_number if logistics else None,
        items=items, status_logs=logs,
        can_pay=order.status == rules.STATUS_PENDING_PAY,
        can_cancel=order.status in rules.CANCELABLE_STATUS,
        can_receive=rules.can_transition(order.status, rules.STATUS_FINISHED),
    )


__all__ = [
    "ShopError", "get_user", "search_products", "product_detail", "list_categories",
    "cart_to_data", "add_to_cart", "update_cart_item", "remove_cart_item",
    "list_addresses", "create_address", "preview", "create_order", "pay_order",
    "cancel_order", "receive_order", "auto_close_expired_orders",
    "list_orders", "order_detail", "usable_coupons",
    "list_user_coupons", "points_summary",
]


def list_user_coupons(
    db: Session, user: models.User, goods_amount: Decimal | None = None,
) -> UserCouponListData:
    """我的优惠券。传入商品金额时，逐张判断当前能不能用并给出原因。"""
    _expire_coupons(db, user)
    rows = db.scalars(
        select(models.UserCoupon)
        .options(joinedload(models.UserCoupon.coupon))
        .filter(models.UserCoupon.user_id == user.id)
        .order_by(models.UserCoupon.id.desc())
    ).all()
    now = rules.now()
    coupons: list[UserCouponData] = []
    usable_count = 0
    for row in rows:
        coupon = row.coupon
        usable = True
        reason = ""
        if row.status == "used":
            usable, reason = False, "已使用"
        elif row.status == "expired" or coupon.end_at < now:
            usable, reason = False, "已过期"
        elif goods_amount is not None and goods_amount < coupon.threshold:
            usable = False
            reason = f"差 {rules.money(coupon.threshold - goods_amount)} 元可用"
        if usable:
            usable_count += 1
        coupons.append(UserCouponData(
            id=row.id, code=coupon.code, name=coupon.name, type=coupon.type,
            threshold=coupon.threshold, amount=coupon.amount, rate=coupon.rate,
            status=row.status, end_at=coupon.end_at, usable=usable, reason=reason,
        ))
    return UserCouponListData(
        user_id=user.user_id, total=len(coupons),
        usable_count=usable_count, coupons=coupons,
    )


def points_summary(db: Session, user: models.User) -> PointsData:
    """积分余额 + 流水。余额以流水为准，避免与 users.points 漂移。"""
    rows = db.scalars(
        select(models.PointsLedger)
        .filter(models.PointsLedger.user_id == user.id)
        .order_by(models.PointsLedger.id.desc())
        .limit(20)
    ).all()
    ledger_total = db.scalar(
        select(func.coalesce(func.sum(models.PointsLedger.change), 0))
        .filter(models.PointsLedger.user_id == user.id)
    )
    balance = int(ledger_total or 0)
    if user.points != balance:
        user.points = balance
        db.commit()
    orders_by_id = {
        order.id: order.order_id
        for order in db.scalars(
            select(models.Order).filter(models.Order.user_id == user.id)).all()
    }
    return PointsData(
        user_id=user.user_id, nickname=user.nickname, level=user.level,
        is_plus=bool(user.is_plus), points=balance, growth=user.growth or 0,
        next_level_points=max(0, rules.POINTS_PER_LEVEL - balance % rules.POINTS_PER_LEVEL),
        ledger=[
            PointsLogData(
                change=row.change, balance_after=row.balance_after, reason=row.reason,
                created_at=row.created_at,
                order_id=orders_by_id.get(row.order_id) if row.order_id else None,
            )
            for row in rows
        ],
    )
