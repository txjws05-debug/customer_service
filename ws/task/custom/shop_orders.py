"""订单查询与收货 action。"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import (
    format_orders,
    resolve_commerce_user,
    shop_get,
    shop_post,
)


class ListMyOrders(Action):
    name = "action_list_my_orders"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        user_id = resolve_commerce_user(state.sender_id)
        status = (slots.get("order_status") or "").strip()

        path = f"/users/{user_id}/orders"
        if status:
            path += f"?status={status}"
        data = await shop_get(path)
        return ActionResult(slot_updates={
            "order_list_summary": format_orders(data),
            "order_total": data.get("total", 0),
        })


class ConfirmReceipt(Action):
    name = "action_confirm_receipt"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        order_number = (slots.get("order_number") or "").strip()
        if not order_number:
            raise ChatServiceError("请告诉我需要确认收货的订单号。")

        received = await shop_post(f"/orders/{order_number}/receive")
        earned = received.get("earned_points") or 0
        summary = (f"订单 {received['order_id']} 已确认收货，"
                   f"订单状态：{received.get('status')}。")
        if earned:
            summary += f"本次获得 {earned} 积分，感谢你的支持！"
        return ActionResult(slot_updates={
            "order_number": received["order_id"],
            "order_status": received["status"],
            "order_summary": summary,
            "receipt_summary": summary,
            "earned_points": earned,
        })
