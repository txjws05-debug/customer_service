from typing import Any

from ws.config.config import settings
from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.http import get_api_data


class LookupOrderStatus(Action):
    name = "action_lookup_order_status"

    async def run(
            self,
            state: DialogueState,
            action_kwargs: dict[str, Any],
    ) -> ActionResult:
        # 1 获取订单编号，从state里面槽位获取到
        order_number = state.tasks.active.slots.get("order_number")
        if not order_number:
            raise ChatServiceError("缺少订单号，无法查询订单状态。")

        # 2 调用中台接口，网络/状态码/JSON 异常由 get_api_data 统一处理
        data = await get_api_data(
            f"{settings.commerce_api_base_url}/orders/{order_number}/status")

        # 3 校验返回字段，避免 KeyError
        if not isinstance(data, dict) or not data.get("status"):
            raise ChatServiceError("订单状态查询结果不完整，请稍后再试。")

        return ActionResult(slot_updates={
            "order_status": data["status"],
            "order_summary": data.get("status_desc") or data["status"],
        })
