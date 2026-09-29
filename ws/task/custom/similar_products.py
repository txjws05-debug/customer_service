from typing import Any

from ws.config.config import settings
from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.http import get_api_data


# 相似商品推荐
class RecommendSimilarProducts(Action):
    name = "action_recommend_similar_products"

    async def run(
            self,
            state: DialogueState,
            action_kwargs: dict[str, Any],
    ) -> ActionResult:
        product_id = state.tasks.active.slots.get("product_id")
        if not product_id:
            raise ChatServiceError(
                "请先选择一个商品，我才能为你推荐相似商品。")

        url = f"{settings.commerce_api_base_url}/products/{product_id}/similar"
        try:
            data = await get_api_data(url)
        except ChatServiceError:
            # 教学中台可能尚未提供“相似商品”接口：给出兜底回复，保证流程能正常走完
            return ActionResult(slot_updates={
                "recommendation_summary":
                    "相似商品推荐正在升级中，暂时无法提供，你可以先咨询其他问题。"
            })

        # data 兼容两种形态：直接是列表，或 {"items": [...]}
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("items", [])
        else:
            items = []

        if not items:
            summary = "暂时没有找到相似商品，你可以看看其他热门商品。"
        else:
            names = [
                str(item.get("name", "商品"))
                for item in items[:5]
                if isinstance(item, dict)
            ]
            summary = "为你找到这些相似商品：" + "、".join(names) + "。"

        return ActionResult(slot_updates={"recommendation_summary": summary})
