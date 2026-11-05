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
    current_on_behalf,
    delete_api_data,
    get_api_data,
    patch_api_data,
    post_api_data,
)

# ============================================================ 用户映射
def current_commerce_user() -> str:
    """本次对话代办的商城号（DialogueService 按账号绑定表注入，见 ws/utils/http.py）。

    不再按用户名推算：那条规则让注册名叫 u1002 的人冒领 u1002，其余人共用 u1001。
    没有绑定时抛业务错误，而不是随便拿一个账号去下单。
    """
    cuid = current_on_behalf()
    if cuid:
        return cuid
    raise ChatServiceError(
        "还没有绑定商城账号，请重新登录后再让我帮你办理下单、售后这类操作。")


async def provision_commerce_account(nickname: str) -> str:
    """注册/首次登录时由中台开一个新的商城账号，返回商城号。不在对话里调用。"""
    data = await post_api_data(shop_url("/users"), {"nickname": nickname})
    if not isinstance(data, dict) or not data.get("user_id"):
        raise ChatServiceError("开通商城账号失败，请稍后再试。")
    return str(data["user_id"])


# 订单号只允许字母数字（线上两种格式：SO+数字/十六进制、B/C+数字）。
# 订单号来自大模型抽槽或 ChatRequest.object，都不可信；带 / . ? % 空格的一律拒绝，
# 否则 "x/../../shop/admin/orders" 会被 httpx 规范化成运营端接口。
_ORDER_REF = re.compile(r"^[A-Za-z0-9]{1,40}$")


def order_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not _ORDER_REF.fullmatch(text):
        raise ChatServiceError("订单号格式不对，请核对后再发我（只包含字母和数字）。")
    return text


# ============================================================ 接口快捷方式
def shop_url(path: str) -> str:
    """拼出交易域地址。path 以 / 开头，例如 /users/u1001/cart。"""
    return f"{settings.commerce_api_base_url.rstrip('/')}/shop{path}"


async def shop_get(path: str) -> Any:
    return await get_api_data(shop_url(path))


async def shop_post(path: str, body: dict | None = None, *,
                    headers: dict | None = None) -> Any:
    return await post_api_data(shop_url(path), body, headers)


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


# 只认「数字 + 量词」：原话里的订单号、价格（「8999 的那个」）不能被当成数量
_QUANTITY_IN_TEXT = re.compile(r"(\d+)\s*(?:台|件|个|部|只|份|套|箱|盒|支)")


def quantity_from_text(text: str | None) -> str:
    """从用户原话里找「999 台」这类数量表达，找不到返回空串。"""
    match = _QUANTITY_IN_TEXT.search(text or "")
    return match.group(0) if match else ""


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
    # 中台的价格是字符串，必须按数值比：字典序下 "10999.00" < "8999.00"，
    # 会把 512G 当成最便宜的选中（多收 2000 元）。缺价/非法价排最后，不能当 0。
    skus.sort(key=_price_key)
    return skus[0]


def _price_key(sku: dict) -> Decimal:
    try:
        price = Decimal(str(sku.get("price")))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("Infinity")
    return price if price.is_finite() and price >= 0 else Decimal("Infinity")
