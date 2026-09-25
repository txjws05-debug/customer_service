from typing import Any

from ws.config.config import settings
from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils import http_client
class LookupOrderStatus(Action):
    name = "action_lookup_order_status"

    async def run(
            self,
            state:DialogueState,
            action_kwargs:dict[str,Any],
                  ) ->ActionResult:

        #1 获取订单编号，从state里面槽位获取到
        order_number=state.tasks.active.get("order_number")
        #2 httpx调用中台接口，路径+参数+提交方式
        url=f"{settings.commerce_api_base_url}/orders/{order_number}/status"
        response = await http_client.http_client.get(url)
        data = response.json()["data"]

        #封装到ActionResult
        return ActionResult(
            slot_updates={
                "order_status":data["status"],
                "order_summary":data ["status_desc"],
            }
        )