from typing import Any

from ws.config.config import settings
from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils import http_client


#查询物流
class LookupTracking(Action):
    name = "action_lookup_logistics"
    async def run(
            self,
            state:DialogueState,
            action_kwargs:dict[str,Any],
                  ) ->ActionResult:

        order_number = state.tasks.active.slots.get("order_number")
        url = f"{settings.commerce_api_base_url}/orders/{order_number}/logistics"
        response = await http_client.http_client.get(url)
        data =response.json()["data"]
        return ActionResult(
            slot_updates={
                "logistics_company":data["logistics_company"],
                "tracking_number":data["tracking_number"],
                "logistics_status":data["status_desc"],
            }
        )