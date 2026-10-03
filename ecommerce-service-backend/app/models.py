"""电商中台的数据模型。

分两块：
1. 原有「只读数据源」部分（用户 / 商品 / 订单 / 物流 / 退款 / 催发货）——
   列名与语义保持不变，只增加了可空列，`ws` 客服端的既有调用不受影响。
2. 新补的「交易闭环」部分（SKU 库存 / 购物车 / 地址 / 支付 / 优惠券 / 积分 /
   售后工单 / 评价 / 状态日志 / 库存流水）。

约定：
- 金额一律 Numeric(10, 2)，用 Decimal 计算，避免浮点误差；
- 订单状态用中文字面量（与既有数据一致），状态机见 app/shop_rules.py；
- `user_id` 在 orders/addresses 等表里是 users.id（自增主键），
  业务上的字符串 ID 是 users.user_id —— 与既有写法保持一致。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ============================================================ 用户域
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(100))
    level: Mapped[str] = mapped_column(String(32))
    mobile_masked: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # 会员与积分：level 用于展示，is_plus 用于规则判断（运费/折扣）
    is_plus: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    growth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    addresses: Mapped[list["Address"]] = relationship(back_populates="user")


class Address(Base):
    """收货地址簿。"""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receiver_name: Mapped[str] = mapped_column(String(64))
    phone_masked: Mapped[str] = mapped_column(String(32))
    province: Mapped[str] = mapped_column(String(32))
    city: Mapped[str] = mapped_column(String(32))
    district: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(255))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="addresses")

    @property
    def full_address(self) -> str:
        return f"{self.province}{self.city}{self.district}{self.detail}"


# ============================================================ 商品域
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # 展示价（最低 SKU 价）
    stock_status: Mapped[str] = mapped_column(String(32))
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attributes_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # 新增：类目 / 品牌 / 上下架 / 评价与销量聚合（列表、搜索、排序要用）
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="在售", server_default="在售")
    rating_avg: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0"), server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sales_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    skus: Mapped[list["ProductSku"]] = relationship(
        back_populates="product", cascade="all, delete-orphan")
    category: Mapped[Category | None] = relationship()


class ProductSku(Base):
    """商品规格。小型版：spec_json 直接存规格字典，不做规格项模板表。"""

    __tablename__ = "product_skus"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    sku_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    spec_json: Mapped[dict] = mapped_column(JSON)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="在售", server_default="在售")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    product: Mapped[Product] = relationship(back_populates="skus")

    @property
    def spec_text(self) -> str:
        return " ".join(f"{k}:{v}" for k, v in (self.spec_json or {}).items())


# ============================================================ 购物车
class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "sku_id", name="ux_cart_user_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("product_skus.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    selected: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    sku: Mapped[ProductSku] = relationship()


# ============================================================ 订单域
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32))
    status_desc: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # 商品总额（历史字段）
    created_at: Mapped[datetime] = mapped_column(DateTime)
    receiver_name: Mapped[str] = mapped_column(String(64))
    receiver_phone_masked: Mapped[str] = mapped_column(String(32))
    receiver_address: Mapped[str] = mapped_column(String(255))

    # 新增：优惠 / 运费 / 实付 / 关联地址与券 / 各状态时间戳
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), server_default="0")
    freight_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), server_default="0")
    # 实付 = amount - discount_amount + freight_amount
    # 历史数据没有这个值，迁移里回填为 amount，读取时用 Order.payable 兜底
    pay_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id"), nullable=True)
    # 用了哪张券通过 user_coupons.order_id 反查——不在这里放 user_coupon_id，
    # 否则与 user_coupons.order_id 形成循环外键，create_all 建表会有麻烦
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    logistics_records: Mapped[list["LogisticsRecord"]] = relationship(back_populates="order")
    refund_requests: Mapped[list["RefundRequest"]] = relationship(back_populates="order")
    shipping_urges: Mapped[list["ShippingUrgeRequest"]] = relationship(back_populates="order")
    status_logs: Mapped[list["OrderStatusLog"]] = relationship(back_populates="order")

    @property
    def payable(self) -> Decimal:
        """应付款；老数据没有 pay_amount 时退回 amount。"""
        return self.pay_amount if self.pay_amount is not None else self.amount


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    title_snapshot: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # 新增：下单时的 SKU 与规格快照——商品日后改规格，历史订单仍要还原当时的样子
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("product_skus.id"), nullable=True)
    spec_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    sku: Mapped[ProductSku | None] = relationship()


class OrderStatusLog(Base):
    """订单状态流转审计。"""

    __tablename__ = "order_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(32), default="system")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[Order] = relationship(back_populates="status_logs")


class Payment(Base):
    """支付流水（mock 支付渠道）。"""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # wechat / alipay / card
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(16))  # success / failed
    trade_no: Mapped[str] = mapped_column(String(64), unique=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime)


class LogisticsRecord(Base):
    __tablename__ = "logistics_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    logistics_company: Mapped[str] = mapped_column(String(64))
    tracking_number: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    status_desc: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[Order] = relationship(back_populates="logistics_records")
    traces: Mapped[list["LogisticsTrace"]] = relationship(back_populates="record")


class LogisticsTrace(Base):
    __tablename__ = "logistics_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    logistics_record_id: Mapped[int] = mapped_column(ForeignKey("logistics_records.id"))
    trace_time: Mapped[datetime] = mapped_column(DateTime)
    trace_desc: Mapped[str] = mapped_column(String(255))

    record: Mapped[LogisticsRecord] = relationship(back_populates="traces")


class RefundRequest(Base):
    """既有接口用的简单退款申请（/orders/{id}/refund-applications）。

    完整的售后流程走 AfterSaleTicket；这里保持原样，兼容客服端既有调用。
    """

    __tablename__ = "refund_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    operator: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    status_desc: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[Order] = relationship(back_populates="refund_requests")


class ShippingUrgeRequest(Base):
    __tablename__ = "shipping_urge_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    urge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    operator: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    status_desc: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[Order] = relationship(back_populates="shipping_urges")


# ============================================================ 售后域
class AfterSaleTicket(Base):
    """售后工单：仅退款 / 退货退款。

    状态机 submitted → approved / rejected → returning → received → completed。
    换货不在小型版范围内（规则组合太多），需要时再扩。
    """

    __tablename__ = "after_sale_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # refund_only / return_refund
    status: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    order: Mapped[Order] = relationship()


class InventoryLog(Base):
    """库存流水：下单扣减、取消回滚、售后退货入库都要留痕。"""

    __tablename__ = "inventory_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("product_skus.id"), index=True)
    change: Mapped[int] = mapped_column(Integer)  # 正数入库、负数出库
    stock_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


# ============================================================ 营销域
class Coupon(Base):
    """优惠券模板：满减（full_reduce）或折扣（discount）。"""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), server_default="0")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)  # 0.900 = 9 折
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    claimed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class UserCoupon(Base):
    __tablename__ = "user_coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"))
    status: Mapped[str] = mapped_column(String(16), default="unused", index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    coupon: Mapped[Coupon] = relationship()


class PointsLedger(Base):
    """积分流水。小型版只做「下单得积分 + 查询」，不做积分抵扣。"""

    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    change: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


# ============================================================ 评价域
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="ux_review_order_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    images_json: Mapped[list] = mapped_column(JSON, default=list)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    append_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    product: Mapped[Product] = relationship()
    user: Mapped[User] = relationship()
