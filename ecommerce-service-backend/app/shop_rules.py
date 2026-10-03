"""电商业务规则集中地：订单/售后状态机、运费、优惠券、积分。

刻意与路由层分开：这些是纯函数 + 常量，不碰数据库，方便单测，
也让「业务规则」在一处可读、可讲（面试时状态图和算钱规则都从这里讲）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# ============================================================ 订单状态机
STATUS_PENDING_PAY = "待付款"
STATUS_PENDING_SHIP = "待发货"
STATUS_PENDING_PICKUP = "待揽收"
STATUS_IN_TRANSIT = "运输中"
STATUS_PENDING_RECEIVE = "待收货"
STATUS_FINISHED = "已完成"
STATUS_CANCELED = "已取消"

STATUS_DESC: dict[str, str] = {
    STATUS_PENDING_PAY: "订单已创建，等待付款。",
    STATUS_PENDING_SHIP: "已付款，商家备货中。",
    STATUS_PENDING_PICKUP: "已出库，等待快递揽收。",
    STATUS_IN_TRANSIT: "包裹运输中。",
    STATUS_PENDING_RECEIVE: "包裹已到达，请确认收货。",
    STATUS_FINISHED: "订单已完成。",
    STATUS_CANCELED: "订单已取消。",
}

# 允许的流转；未列出的组合一律拒绝（例如「已完成」不能再发货）
ORDER_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PENDING_PAY: {STATUS_PENDING_SHIP, STATUS_CANCELED},
    STATUS_PENDING_SHIP: {STATUS_PENDING_PICKUP, STATUS_CANCELED},
    STATUS_PENDING_PICKUP: {STATUS_IN_TRANSIT},
    STATUS_IN_TRANSIT: {STATUS_PENDING_RECEIVE},
    STATUS_PENDING_RECEIVE: {STATUS_FINISHED},
    STATUS_FINISHED: set(),
    STATUS_CANCELED: set(),
}

# 待付款订单的自动关单时限
AUTO_CLOSE_AFTER = timedelta(minutes=30)

# 可以申请售后的状态（付款之后、完成之后都允许）
AFTER_SALE_ALLOWED_STATUS = {
    STATUS_PENDING_SHIP,
    STATUS_PENDING_PICKUP,
    STATUS_IN_TRANSIT,
    STATUS_PENDING_RECEIVE,
    STATUS_FINISHED,
}

# 可以取消订单的状态（未发货前）
CANCELABLE_STATUS = {STATUS_PENDING_PAY, STATUS_PENDING_SHIP}


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ORDER_TRANSITIONS.get(from_status, set())


def describe(status: str) -> str:
    return STATUS_DESC.get(status, status)


# ============================================================ 售后状态机
AS_SUBMITTED = "submitted"
AS_APPROVED = "approved"
AS_REJECTED = "rejected"
AS_RETURNING = "returning"
AS_RECEIVED = "received"
AS_COMPLETED = "completed"
AS_CANCELED = "canceled"

AFTER_SALE_DESC: dict[str, str] = {
    AS_SUBMITTED: "售后申请已提交，等待审核。",
    AS_APPROVED: "审核通过，退货退款请按提示寄回商品。",
    AS_REJECTED: "审核未通过。",
    AS_RETURNING: "商品寄回中。",
    AS_RECEIVED: "商家已收到退货，验收中。",
    AS_COMPLETED: "售后已完成，退款将原路返回。",
    AS_CANCELED: "售后申请已撤销。",
}

AFTER_SALE_TRANSITIONS: dict[str, set[str]] = {
    AS_SUBMITTED: {AS_APPROVED, AS_REJECTED, AS_CANCELED},
    AS_APPROVED: {AS_RETURNING, AS_COMPLETED, AS_CANCELED},  # 仅退款可直接完成
    AS_RETURNING: {AS_RECEIVED},
    AS_RECEIVED: {AS_COMPLETED, AS_REJECTED},
    AS_REJECTED: set(),
    AS_COMPLETED: set(),
    AS_CANCELED: set(),
}

AFTER_SALE_TYPE_DESC = {
    "refund_only": "仅退款（不退货）",
    "return_refund": "退货退款",
}


def can_transition_after_sale(from_status: str, to_status: str) -> bool:
    return to_status in AFTER_SALE_TRANSITIONS.get(from_status, set())


def describe_after_sale(status: str) -> str:
    return AFTER_SALE_DESC.get(status, status)


# ============================================================ 运费与算钱
CENTS = Decimal("0.01")
FREE_FREIGHT_THRESHOLD = Decimal("99")   # 满 99 包邮
DEFAULT_FREIGHT = Decimal("8")           # 否则 8 元


def money(value: Decimal | int | float | str) -> Decimal:
    """统一保留两位小数，四舍五入。"""
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def compute_freight(goods_amount: Decimal, is_plus: bool = False) -> Decimal:
    """运费：PLUS 会员免运费；否则满 99 包邮，其余 8 元。"""
    if is_plus:
        return Decimal("0")
    if goods_amount >= FREE_FREIGHT_THRESHOLD:
        return Decimal("0")
    return DEFAULT_FREIGHT


def compute_coupon_discount(
    coupon_type: str,
    amount: Decimal,
    threshold: Decimal,
    coupon_amount: Decimal | None = None,
    rate: Decimal | None = None,
) -> Decimal:
    """优惠券能减多少钱。

    - full_reduce：满 threshold 减 amount，不满门槛不优惠；
    - discount：满 threshold 后按 rate 打折（0.9 = 9 折），减掉的部分即优惠额。
    折扣券的优惠额不会超过商品总额。
    """
    if amount < threshold:
        return Decimal("0")

    if coupon_type == "full_reduce":
        if coupon_amount is None:
            return Decimal("0")
        # 优惠不能超过商品金额
        return money(min(coupon_amount, amount))

    if coupon_type == "discount":
        if rate is None:
            return Decimal("0")
        return money(amount * (Decimal("1") - rate))

    return Decimal("0")


def compute_pay_amount(goods_amount: Decimal, discount: Decimal, freight: Decimal) -> Decimal:
    """实付 = 商品总额 - 优惠 + 运费，且不低于 0.01（避免 0 元订单）。"""
    pay = money(goods_amount - discount + freight)
    return pay if pay > 0 else CENTS


# ============================================================ 积分
POINTS_PER_YUAN = 1          # 普通会员：每实付 1 元得 1 积分
POINTS_PER_YUAN_PLUS = 2     # PLUS 会员双倍


def calc_points(pay_amount: Decimal, is_plus: bool = False) -> int:
    rate = POINTS_PER_YUAN_PLUS if is_plus else POINTS_PER_YUAN
    return int(pay_amount) * rate


def calc_growth(pay_amount: Decimal) -> int:
    """成长值：与实付金额 1:1。"""
    return int(pay_amount)


# ============================================================ 其它
def now() -> datetime:
    return datetime.now()


def new_order_no() -> str:
    from uuid import uuid4

    return f"SO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"


def new_ticket_no() -> str:
    from uuid import uuid4

    return f"AS{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"
