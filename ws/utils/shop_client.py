"""客服 Agent 与电商交易域（/shop/*）之间的胶水层。

放三样东西：
1. 登录用户 → 商城用户号的映射；
2. /shop 路径拼装与四个 HTTP 方法的快捷方式；
3. 把中台返回的结构化数据渲染成客服话术（action 只负责取数，文案统一在这里）。

为什么单独一层：action 里如果各写各的 URL 和文案，改一处字段就要翻十个文件；
集中之后「交易能力」的接入点只有一个文件，也便于单测。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ws.config.config import settings
from ws.utils.errors import ChatServiceError
from ws.utils.http import (
    delete_api_data,
    get_api_data,
    patch_api_data,
    post_api_data,
)

_MERCHANT_USER_PATTERN = re.compile(r"^u\d+$")


# ============================================================ 用户映射
def resolve_commerce_user(sender_id: str | None) -> str:
    """把登录用户名映射成商城用户号。

    真实系统里这一步查「账号绑定」表（用户在个人中心绑定商城账号）。
    演示环境用两条规则：
    1) 登录名本身就是商城号（如 u1001）→ 直接用；
    2) 否则用 COMMERCE_DEFAULT_USER_ID（默认 u1001），保证加购/下单能演示。
    都不成立时抛业务错误，而不是随便拿一个账号去下单——那是把别人的订单
    当成自己的，属于隐私与资损问题。
    """
    candidate = (sender_id or "").strip()
    if candidate and _MERCHANT_USER_PATTERN.match(candidate):
        return candidate
    fallback = (settings.commerce_default_user_id or "").strip()
    if fallback:
        return fallback
    raise ChatServiceError(
        "还没有绑定商城账号，请先在个人中心绑定后，再让我帮你办理下单、售后这类操作。")


# ============================================================ 接口快捷方式
def shop_url(path: str) -> str:
    """拼出交易域地址。path 以 / 开头，例如 /users/u1001/cart。"""
    return f"{settings.commerce_api_base_url.rstrip('/')}/shop{path}"


async def shop_get(path: str) -> Any:
    return await get_api_data(shop_url(path))


async def shop_post(path: str, body: dict | None = None) -> Any:
    return await post_api_data(shop_url(path), body)


async def shop_patch(path: str, body: dict | None = None) -> Any:
    return await patch_api_data(shop_url(path), body)


async def shop_delete(path: str) -> Any:
    return await delete_api_data(shop_url(path))


# ============================================================ 文案渲染
def money(value: Any) -> str:
    try:
        return f"¥{Decimal(str(value)):.2f}"
    except (InvalidOperation, TypeError):
        return f"¥{value}"


def format_cart(cart: dict) -> str:
    items = cart.get("items") or []
    if not items:
        return "购物车还是空的。"
    lines = [f"购物车共 {cart.get('total_quantity', 0)} 件商品："]
    for index, item in enumerate(items, start=1):
        spec = f"（{item['spec_text']}）" if item.get("spec_text") else ""
        flag = "" if item.get("available", True) else "（库存不足）"
        lines.append(
            f"{index}. {item['title']}{spec} ×{item['quantity']} "
            f"{money(item['price'])} {flag}")
    lines.append(f"已勾选 {cart.get('selected_quantity', 0)} 件，"
                 f"合计 {money(cart.get('selected_amount'))}。")
    return "\n".join(lines)


def format_coupons(data: dict) -> str:
    coupons = data.get("coupons") or []
    if not coupons:
        return "你名下暂时没有优惠券。"
    usable = [c for c in coupons if c.get("usable")]
    lines = [f"你有 {data.get('total', len(coupons))} 张券，"
             f"当前可用 {data.get('usable_count', len(usable))} 张："]
    for coupon in coupons[:5]:
        value = (f"减{money(coupon['amount'])}" if coupon.get("type") == "full_reduce"
                 else f"{(Decimal(str(coupon['rate'])) * 10):.1f}折")
        state = "可用" if coupon.get("usable") else (coupon.get("reason") or "不可用")
        lines.append(
            f"- {coupon['name']}（满{money(coupon['threshold'])}可用，{value}）：{state}")
    return "\n".join(lines)


def format_points(data: dict) -> str:
    return (f"你当前有 {data.get('points', 0)} 积分，会员等级 {data.get('level', '')}，"
            f"成长值 {data.get('growth', 0)}，"
            f"距离下一等级还差 {data.get('next_level_points', 0)} 积分。")


def _clean(text: Any) -> str:
    """中台的状态说明自带句号，拼进我们的话术时会出现「。。」，统一去掉。"""
    return str(text or "").strip().rstrip("。").strip()


def format_order_brief(order: dict) -> str:
    desc = _clean(order.get("status_desc") or order.get("status"))
    return (f"订单 {order.get('order_id')}：{order.get('title', '')} "
            f"{desc}，实付 {money(order.get('pay_amount'))}。")


def format_orders(data: dict) -> str:
    orders = data.get("orders") or []
    if not orders:
        return "没有查询到符合条件的订单。"
    lines = [f"共 {data.get('total', len(orders))} 笔订单："]
    for order in orders[:5]:
        lines.append("- " + format_order_brief(order))
    if len(orders) > 5:
        lines.append("（只展示最近 5 笔）")
    return "\n".join(lines)


def format_products(data: dict) -> str:
    items = data.get("items") or []
    if not items:
        return "没有找到符合条件的商品。"
    lines = [f"为你找到 {data.get('total', len(items))} 个商品："]
    for item in items[:5]:
        rating = (f"评分 {item['rating_avg']}" if item.get("rating_count") else "暂无评价")
        lines.append(
            f"- {item['title']}（{item.get('brand') or ''}）{money(item['price'])}，"
            f"{rating}，已售 {item.get('sales_count', 0)}")
    return "\n".join(lines)


def format_preview(preview: dict) -> str:
    parts = [
        f"商品金额 {money(preview.get('goods_amount'))}",
        f"优惠 -{money(preview.get('discount_amount'))}",
        f"运费 {money(preview.get('freight_amount'))}",
        f"应付 {money(preview.get('pay_amount'))}",
    ]
    text = "、".join(parts) + "。"
    if preview.get("coupon_message"):
        text += f"（{preview['coupon_message']}）"
    if preview.get("receiver_address"):
        text += f" 收货地址：{preview['receiver_address']}"
    return text


_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_quantity(value: Any, default: int = 1) -> int:
    """把「两件」「2 个」「买 3 份」都解析成数量，并夹在 1~99。"""
    if value is None or value == "":
        return default
    if isinstance(value, int):
        number = value
    else:
        text = str(value).strip()
        match = re.search(r"\d+", text)
        if match:
            number = int(match.group())
        else:
            # 中文数字：找出出现的数字字（「两件」「三份」都只含一个）
            found = [digit for char in text for digit in [ _CN_DIGITS.get(char) ] if digit]
            if len(found) == 1:
                number = found[0]
            elif text.startswith("十"):
                number = 10
            elif len(found) > 1:
                # 像「二十三」这种：十位 + 个位，做个简单还原
                number = sum(found)
            else:
                return default
    return max(1, min(99, number))


def format_after_sale(ticket: dict) -> str:
    return (f"售后单 {ticket.get('ticket_no')} 已提交，类型：{ticket.get('type_desc')}，"
            f"退款金额 {money(ticket.get('refund_amount'))}，"
            f"当前状态：{_clean(ticket.get('status_desc'))}。")


async def fetch_default_sku(product_id: str) -> dict:
    """取商品的一个可售规格。

    聊天里让用户念「SKU10001-02」不现实，所以拿不到 sku_code 时，
    自动挑一个在售且有库存的规格（优先最便宜），并把选中的规格告诉用户，
    用户想换规格时再说一声即可。
    """
    detail = await shop_get(f"/products/{product_id}")
    skus = [s for s in (detail.get("skus") or [])
            if s.get("status") == "在售" and (s.get("stock") or 0) > 0]
    if not skus:
        raise ChatServiceError(f"「{detail.get('title', product_id)}」暂时没有可售规格。")
    skus.sort(key=lambda s: s.get("price") or 0)
    return skus[0]
