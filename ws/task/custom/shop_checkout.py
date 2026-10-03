"""下单与支付 action。

下单只创建订单（进入「待付款」，30 分钟未支付会自动关闭并归还库存与优惠券），
不直接扣款；支付是独立的一步，用户明确说「支付」才走。

两种下单模式由流程 YAML 通过 args.mode 指定：
- cart（默认）：结算购物车中已勾选的商品；
- direct：直接购买当前商品（立即购买）。
"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import (
    money,
    parse_quantity,
    resolve_commerce_user,
    shop_post,
)
from ws.task.custom.shop_cart import _resolve_sku


class PlaceOrder(Action):
    name = "action_place_order"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        user_id = resolve_commerce_user(state.sender_id)
        mode = (action_kwargs or {}).get("mode", "cart")

        body: dict[str, Any] = {"user_id": user_id}
        coupon_code = (slots.get("coupon_code") or "").strip()
        if coupon_code:
            body["coupon_code"] = coupon_code

        if mode == "direct":
            sku_code, spec_text = await _resolve_sku(slots, state.share.focuse_object)
            quantity = parse_quantity(slots.get("quantity"))
            body["items"] = [{"sku_code": sku_code, "quantity": quantity}]
            slots["sku_code"] = sku_code
            slots["sku_spec"] = spec_text
            slots["quantity"] = quantity

        order = await shop_post("/orders", body)

        discount = order.get("discount_amount")
        freight = order.get("freight_amount")
        detail = (f"商品金额 {money(order.get('goods_amount'))}，"
                  f"优惠 -{money(discount)}，运费 {money(freight)}，"
                  f"应付 {money(order.get('pay_amount'))}")
        # 用状态名而不是中台的 status_desc：后者自带句号，拼进来会变成「（…。）」
        summary = (f"订单 {order['order_id']} 已创建（{order.get('status')}）。{detail}。"
                   f"请在 {order.get('expires_in_minutes', 30)} 分钟内完成支付，"
                   f"否则订单会自动关闭。需要我现在帮你支付吗？")
        return ActionResult(slot_updates={
            # 写回 order_number：用户接着说「支付」时，支付流程能直接衔接上
            "order_number": order["order_id"],
            "order_status": order["status"],
            "order_summary": summary,
            "pay_amount": order.get("pay_amount"),
            "coupon_message": (f"已使用优惠券 {coupon_code}" if order.get("coupon_code") else ""),
        })


class PayOrder(Action):
    name = "action_pay_order"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        order_number = (slots.get("order_number") or "").strip()
        if not order_number:
            raise ChatServiceError("请告诉我需要支付的订单号。")
        channel = (slots.get("pay_channel") or "wechat").strip()

        paid = await shop_post(f"/orders/{order_number}/pay", {"channel": channel})
        summary = (f"订单 {paid['order_id']} 支付成功，"
                   f"支付金额 {money(paid.get('amount'))}，交易号 {paid.get('trade_no')}。"
                   f"当前状态：{paid.get('status_desc')}")
        return ActionResult(slot_updates={
            "order_number": paid["order_id"],
            "order_status": paid["status"],
            "order_summary": summary,
            "pay_status": paid.get("status"),
            "trade_no": paid.get("trade_no"),
        })
