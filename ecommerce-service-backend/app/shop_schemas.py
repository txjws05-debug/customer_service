"""交易域（/shop/*）的请求与响应模型。

与既有 app/schemas.py 分开：老接口的契约已经上线被客服 Agent 使用，
这里只描述新交易域，改动互不影响。
金额统一 Decimal，响应仍包在既有 ApiResponse({code,message,data}) 信封里。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 商品与搜索
class SkuData(BaseModel):
    sku_id: int
    sku_code: str
    spec: dict[str, Any]
    spec_text: str
    price: Decimal
    original_price: Decimal | None = None
    stock: int
    status: str


class ProductListItem(BaseModel):
    product_id: str
    title: str
    price: Decimal
    cover_url: str | None = None
    category: str | None = None
    brand: str | None = None
    stock_status: str
    rating_avg: Decimal
    rating_count: int
    sales_count: int


class ProductListData(BaseModel):
    total: int
    page: int
    page_size: int
    keyword: str | None = None
    items: list[ProductListItem]


class ProductDetailData(BaseModel):
    product_id: str
    title: str
    description: str
    cover_url: str | None = None
    category: str | None = None
    brand: str | None = None
    status: str
    rating_avg: Decimal
    rating_count: int
    sales_count: int
    attributes: dict[str, Any]
    skus: list[SkuData]


class CategoryData(BaseModel):
    id: int
    name: str
    product_count: int


# ---------------------------------------------------------------- 购物车
class CartAddRequest(BaseModel):
    sku_code: str = Field(description="规格编码，如 SKU10001-01")
    quantity: int = Field(default=1, ge=1, le=99)


class CartUpdateRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=99)
    selected: bool | None = None


class CartLineData(BaseModel):
    item_id: int
    sku_id: int
    sku_code: str
    product_id: str
    title: str
    spec_text: str
    cover_url: str | None = None
    price: Decimal
    quantity: int
    selected: bool
    stock: int
    available: bool
    subtotal: Decimal


class CartData(BaseModel):
    user_id: str
    items: list[CartLineData]
    total_quantity: int
    selected_quantity: int
    selected_amount: Decimal


# ---------------------------------------------------------------- 地址
class AddressCreateRequest(BaseModel):
    receiver_name: str = Field(min_length=1, max_length=64)
    phone_masked: str = Field(min_length=1, max_length=32)
    province: str = Field(min_length=1, max_length=32)
    city: str = Field(min_length=1, max_length=32)
    district: str = Field(min_length=1, max_length=32)
    detail: str = Field(min_length=1, max_length=255)
    is_default: bool = False


class AddressData(BaseModel):
    id: int
    receiver_name: str
    phone_masked: str
    full_address: str
    is_default: bool


class AddressListData(BaseModel):
    user_id: str
    addresses: list[AddressData]


# ---------------------------------------------------------------- 结算与下单
class CouponInfo(BaseModel):
    code: str
    name: str
    type: str
    threshold: Decimal
    amount: Decimal | None = None
    rate: Decimal | None = None
    end_at: datetime


class AmountPreviewData(BaseModel):
    goods_amount: Decimal
    discount_amount: Decimal
    freight_amount: Decimal
    pay_amount: Decimal
    is_plus: bool
    free_freight_threshold: Decimal
    coupon: CouponInfo | None = None
    coupon_message: str = ""
    address_id: int | None = None
    receiver_address: str | None = None


class PreviewRequest(BaseModel):
    coupon_code: str | None = None
    address_id: int | None = None


class OrderItemInput(BaseModel):
    sku_code: str
    quantity: int = Field(default=1, ge=1, le=99)


class OrderCreateRequest(BaseModel):
    user_id: str = Field(description="业务用户号，如 u1001")
    address_id: int | None = Field(default=None, description="不传则用默认地址")
    coupon_code: str | None = None
    # 传 items = 直接购买；不传则结算购物车中已勾选的商品
    items: list[OrderItemInput] | None = None


class OrderItemData(BaseModel):
    product_id: str
    title: str
    spec_text: str | None = None
    quantity: int
    price: Decimal
    subtotal: Decimal


class OrderStatusLogData(BaseModel):
    from_status: str | None = None
    to_status: str
    operator: str
    remark: str | None = None
    created_at: datetime


class OrderListItem(BaseModel):
    order_id: str
    status: str
    status_desc: str
    pay_amount: Decimal
    quantity: int
    title: str
    cover_url: str | None = None
    created_at: datetime


class OrderListData(BaseModel):
    user_id: str
    total: int
    orders: list[OrderListItem]


class ShopOrderDetailData(BaseModel):
    order_id: str
    status: str
    status_desc: str
    created_at: datetime
    paid_at: datetime | None = None
    shipped_at: datetime | None = None
    received_at: datetime | None = None
    goods_amount: Decimal
    discount_amount: Decimal
    freight_amount: Decimal
    pay_amount: Decimal
    is_plus: bool
    receiver_name: str
    receiver_phone_masked: str
    receiver_address: str
    logistics_company: str | None = None
    tracking_number: str | None = None
    items: list[OrderItemData]
    status_logs: list[OrderStatusLogData]
    can_pay: bool
    can_cancel: bool
    can_receive: bool


class OrderCreatedData(BaseModel):
    order_id: str
    status: str
    status_desc: str
    goods_amount: Decimal
    discount_amount: Decimal
    freight_amount: Decimal
    pay_amount: Decimal
    coupon_code: str | None = None
    expires_in_minutes: int


class PayRequest(BaseModel):
    channel: str = Field(default="wechat", description="wechat / alipay / card")


class PayData(BaseModel):
    order_id: str
    trade_no: str
    channel: str
    amount: Decimal
    status: str
    status_desc: str
    paid_at: datetime


class CancelRequest(BaseModel):
    reason: str = Field(default="用户主动取消", max_length=128)


class OrderActionResult(BaseModel):
    order_id: str
    status: str
    status_desc: str
    refunded_points: int = 0
    earned_points: int = 0
    pay_amount: Decimal | None = None


# ---------------------------------------------------------------- 优惠券与积分
class UserCouponData(BaseModel):
    id: int
    code: str
    name: str
    type: str
    threshold: Decimal
    amount: Decimal | None = None
    rate: Decimal | None = None
    status: str
    end_at: datetime
    usable: bool = False
    reason: str = ""


class UserCouponListData(BaseModel):
    user_id: str
    total: int
    usable_count: int
    coupons: list[UserCouponData]


class PointsLogData(BaseModel):
    change: int
    balance_after: int
    reason: str
    created_at: datetime
    order_id: str | None = None


class PointsData(BaseModel):
    user_id: str
    nickname: str
    level: str
    is_plus: bool
    points: int
    growth: int
    next_level_points: int
    ledger: list[PointsLogData]
