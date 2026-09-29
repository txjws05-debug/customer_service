from typing import Any

from ws.config.config import settings
from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.http import get_api_data


# 查询物流
class LookupTracking(Action):
    name = "action_lookup_logistics"

    async def run(
            self,
            state: DialogueState,
            action_kwargs: dict[str, Any],
    ) -> ActionResult:
        order_number = state.tasks.active.slots.get("order_number")
        if not order_number:
            raise ChatServiceError("缺少订单号，无法查询物流。")

        url = f"{settings.commerce_api_base_url}/orders/{order_number}/logistics"
        data = await get_api_data(url)

        # 物流单号是后续展示的必需字段
        if not isinstance(data, dict) or not data.get("tracking_number"):
            raise ChatServiceError("物流信息查询结果不完整，请稍后再试。")

        return ActionResult(slot_updates={
            "logistics_company": data.get("logistics_company", "未知"),
            "tracking_number": data["tracking_number"],
            "logistics_status": data.get("status_desc", "暂无进度"),
        })
