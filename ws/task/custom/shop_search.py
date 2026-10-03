"""商品搜索 action：支持关键词、价格区间与排序。"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.shop_client import (
    format_products,
    shop_get,
)


class SearchProducts(Action):
    name = "action_search_products"
    # 中台只认这几种排序，其它值一律回落到默认排序
    _SORTS = {"default", "sales", "rating", "price_asc", "price_desc", "newest"}

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        keyword = (slots.get("keyword") or "").strip()

        params = ["page_size=5"]
        if keyword:
            params.append(f"q={keyword}")
        for slot_name, param_name in (("max_price", "max_price"),
                                      ("min_price", "min_price"),
                                      ("category_id", "category_id")):
            value = slots.get(slot_name)
            if value not in (None, ""):
                params.append(f"{param_name}={value}")
        sort = (slots.get("sort") or "").strip()
        if sort in self._SORTS and sort != "default":
            params.append(f"sort={sort}")

        data = await shop_get("/products?" + "&".join(params))
        return ActionResult(slot_updates={
            "search_summary": format_products(data),
            "search_total": data.get("total", 0),
            "keyword": keyword,
        })
