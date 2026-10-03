"""售后 action：申请售后（仅退款 / 退货退款）。"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import (
    format_after_sale,
    resolve_commerce_user,
    shop_post,
)

# 用户在对话里说的是自然语言，这里做一次归一化，避免因为措辞不同就走错分支
_RETURN_KEYWORDS = ("退货", "寄回", "退回", "退回去")
_REFUND_ONLY_KEYWORDS = ("仅退款", "只退款", "不退货", "不用退")


def normalize_after_sale_type(raw: str | None) -> str:
    """把用户/模型给的类型归一化成 refund_only 或 return_refund。"""
    text = (raw or "").strip()
    if text in {"refund_only", "return_refund"}:
        return text
    lowered = text.lower()
    if lowered in {"refund_only", "return_refund"}:
        return lowered
    if any(word in text for word in _REFUND_ONLY_KEYWORDS):
        return "refund_only"
    if any(word in text for word in _RETURN_KEYWORDS):
        return "return_refund"
    # 说不清时按「仅退款」处理：不需要用户先寄回，可撤销、代价最小
    return "refund_only"


class ApplyAfterSale(Action):
    name = "action_apply_after_sale"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        user_id = resolve_commerce_user(state.sender_id)
        order_number = (slots.get("order_number") or "").strip()
        if not order_number:
            raise ChatServiceError("请告诉我需要申请售后的订单号。")
        reason = (slots.get("refund_reason") or "").strip()
        if not reason:
            raise ChatServiceError("请简单说明一下申请售后的原因。")

        ticket = await shop_post(f"/orders/{order_number}/after-sales", {
            "user_id": user_id,
            "type": normalize_after_sale_type(slots.get("after_sale_type")),
            "reason": reason,
        })
        return ActionResult(slot_updates={
            "order_number": order_number,
            "after_sale_no": ticket.get("ticket_no"),
            "after_sale_status": ticket.get("status"),
            "after_sale_summary": format_after_sale(ticket) + "。审核结果我会在这里同步给你。",
            "after_sale_type": ticket.get("type"),
        })
