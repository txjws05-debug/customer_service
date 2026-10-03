"""app/shop_rules.py 的单元测试。

这些都是纯函数（不碰数据库），是整个交易链路的「算钱与状态」地基，
必须钉死：
- 运费：PLUS 免运费 / 满 99 包邮 / 否则 8 元
- 优惠券：满减券不满门槛不优惠；折扣券按 rate 打折；优惠额不超过商品总额
- 实付：商品总额 − 优惠 + 运费，且不为 0（避免 0 元订单）
- 积分：普通会员 1 元 1 分、PLUS 双倍
- 状态机：非法流转必须被拒绝（例如「已完成」不能再发货）
"""

from decimal import Decimal

from app import shop_rules as rules


# ---------------------------------------------------------------- 运费
def test_freight_is_free_for_plus_member():
    assert rules.compute_freight(Decimal("1.00"), is_plus=True) == Decimal("0")


def test_freight_is_free_when_reaching_threshold():
    assert rules.compute_freight(Decimal("99.00")) == Decimal("0")
    assert rules.compute_freight(Decimal("150.00")) == Decimal("0")


def test_freight_is_charged_below_threshold():
    assert rules.compute_freight(Decimal("98.99")) == Decimal("8.00")


# ---------------------------------------------------------------- 优惠券
def test_full_reduce_coupon_below_threshold_gives_nothing():
    discount = rules.compute_coupon_discount(
        "full_reduce", Decimal("99.00"), Decimal("100"), Decimal("10"))
    assert discount == Decimal("0.00")


def test_full_reduce_coupon_at_threshold():
    discount = rules.compute_coupon_discount(
        "full_reduce", Decimal("100.00"), Decimal("100"), Decimal("10"))
    assert discount == Decimal("10.00")


def test_full_reduce_discount_never_exceeds_goods_amount():
    """满 100 减 500 这种配置错误也不能把订单算成负数。"""
    discount = rules.compute_coupon_discount(
        "full_reduce", Decimal("120.00"), Decimal("100"), Decimal("500"))
    assert discount == Decimal("120.00")


def test_discount_coupon_uses_rate():
    # 9 折：1000 元商品减 100
    discount = rules.compute_coupon_discount(
        "discount", Decimal("1000.00"), Decimal("199"), None, Decimal("0.900"))
    assert discount == Decimal("100.00")


def test_discount_coupon_below_threshold_gives_nothing():
    discount = rules.compute_coupon_discount(
        "discount", Decimal("198.99"), Decimal("199"), None, Decimal("0.900"))
    assert discount == Decimal("0.00")


# ---------------------------------------------------------------- 实付金额
def test_pay_amount_is_goods_minus_discount_plus_freight():
    pay = rules.compute_pay_amount(
        Decimal("100.00"), Decimal("10.00"), Decimal("8.00"))
    assert pay == Decimal("98.00")


def test_pay_amount_never_zero():
    """优惠把商品金额抵完时，仍保留最小金额而不是 0 元订单。"""
    pay = rules.compute_pay_amount(
        Decimal("10.00"), Decimal("10.00"), Decimal("0"))
    assert pay == Decimal("0.01")


def test_money_rounds_half_up():
    assert rules.money(Decimal("1.005")) == Decimal("1.01")
    assert rules.money("2.344") == Decimal("2.34")


# ---------------------------------------------------------------- 积分
def test_points_normal_member():
    assert rules.calc_points(Decimal("149.00"), is_plus=False) == 149


def test_points_plus_member_is_double():
    assert rules.calc_points(Decimal("14.90"), is_plus=True) == 28  # int(14.9)=14 → ×2


def test_growth_equals_pay_amount():
    assert rules.calc_growth(Decimal("99.90")) == 99


# ---------------------------------------------------------------- 状态机
def test_order_happy_path_is_allowed():
    chain = [
        (rules.STATUS_PENDING_PAY, rules.STATUS_PENDING_SHIP),
        (rules.STATUS_PENDING_SHIP, rules.STATUS_PENDING_PICKUP),
        (rules.STATUS_PENDING_PICKUP, rules.STATUS_IN_TRANSIT),
        (rules.STATUS_IN_TRANSIT, rules.STATUS_PENDING_RECEIVE),
        (rules.STATUS_PENDING_RECEIVE, rules.STATUS_FINISHED),
    ]
    for from_status, to_status in chain:
        assert rules.can_transition(from_status, to_status), f"{from_status}→{to_status} 应允许"


def test_order_illegal_transitions_are_rejected():
    assert not rules.can_transition(rules.STATUS_FINISHED, rules.STATUS_PENDING_SHIP)
    assert not rules.can_transition(rules.STATUS_CANCELED, rules.STATUS_PENDING_SHIP)
    assert not rules.can_transition(rules.STATUS_PENDING_PAY, rules.STATUS_FINISHED)
    assert not rules.can_transition(rules.STATUS_IN_TRANSIT, rules.STATUS_CANCELED)


def test_cancel_only_before_shipping():
    assert rules.STATUS_PENDING_PAY in rules.CANCELABLE_STATUS
    assert rules.STATUS_PENDING_SHIP in rules.CANCELABLE_STATUS
    assert rules.STATUS_IN_TRANSIT not in rules.CANCELABLE_STATUS


def test_after_sale_transitions():
    assert rules.can_transition_after_sale(rules.AS_SUBMITTED, rules.AS_APPROVED)
    assert rules.can_transition_after_sale(rules.AS_SUBMITTED, rules.AS_REJECTED)
    assert rules.can_transition_after_sale(rules.AS_RETURNING, rules.AS_RECEIVED)
    assert rules.can_transition_after_sale(rules.AS_RECEIVED, rules.AS_COMPLETED)
    # 已完成的工单不能再流转；退货退款不能跳过寄回直接完成
    assert not rules.can_transition_after_sale(rules.AS_COMPLETED, rules.AS_APPROVED)
    assert not rules.can_transition_after_sale(rules.AS_RETURNING, rules.AS_COMPLETED)


def test_status_descriptions_cover_all_statuses():
    """每个状态都要有可读说明，前端和客服话术直接用它们。"""
    for status in rules.ORDER_TRANSITIONS:
        assert status in rules.STATUS_DESC, f"{status} 缺少说明"
    for status in rules.AFTER_SALE_TRANSITIONS:
        assert status in rules.AFTER_SALE_DESC, f"{status} 缺少说明"
