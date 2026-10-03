"""营销相关 action：我的优惠券、我的积分。"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.shop_client import (
    format_coupons,
    format_points,
    resolve_commerce_user,
    shop_get,
)


class ListMyCoupons(Action):
    name = "action_list_my_coupons"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        user_id = resolve_commerce_user(state.sender_id)

        path = f"/users/{user_id}/coupons"
        # 带了商品金额就顺便告诉用户「这单能不能用券」，更贴合真实咨询
        goods_amount = slots.get("goods_amount")
        if goods_amount:
            path += f"?goods_amount={goods_amount}"
        data = await shop_get(path)
        return ActionResult(slot_updates={
            "coupon_summary": format_coupons(data),
            "coupon_usable_count": data.get("usable_count", 0),
        })


class MyPoints(Action):
    name = "action_my_points"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        user_id = resolve_commerce_user(state.sender_id)
        data = await shop_get(f"/users/{user_id}/points")
        return ActionResult(slot_updates={
            "points_summary": format_points(data),
            "points": data.get("points", 0),
        })
