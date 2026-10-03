"""购物车相关 action：加购、查看购物车。

聊天里让用户念「SKU10001-02」不现实，所以规格优先从聚焦商品自动挑一个在售
规格（见 shop_client.fetch_default_sku），并把选中的规格回给用户确认。
"""

from typing import Any

from ws.domain.state import DialogueState
from ws.task.action.base import Action, ActionResult
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import (
    fetch_default_sku,
    format_cart,
    parse_quantity,
    resolve_commerce_user,
    shop_get,
    shop_post,
)


async def _resolve_sku(slots: dict, focused=None) -> tuple[str, str]:
    """返回 (sku_code, spec_text)。已有 sku_code 就直接用，否则按商品挑一个。

    商品来源有两条：槽位 product_id（流程的 collect 步会从聚焦对象自动填），
    以及直接看聚焦对象 —— 后者保证即使 collect 步没跑过（例如换了一种入口
    进到 action），加购依然能用。
    """
    sku_code = (slots.get("sku_code") or "").strip()
    if sku_code:
        return sku_code, (slots.get("sku_spec") or "").strip()
    product_id = (slots.get("product_id") or "").strip()
    if not product_id and focused is not None and getattr(focused, "type", None) == "product":
        product_id = focused.id or ""
    if not product_id:
        raise ChatServiceError(
            "请先打开或选择要购买的商品，再来告诉我加购；也可以直接说商品名让我帮你找。")
    sku = await fetch_default_sku(product_id)
    return sku["sku_code"], sku.get("spec_text") or ""


class AddToCart(Action):
    name = "action_add_to_cart"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        slots = state.tasks.active.slots
        user_id = resolve_commerce_user(state.sender_id)
        quantity = parse_quantity(slots.get("quantity"))
        sku_code, spec_text = await _resolve_sku(slots, state.share.focuse_object)

        cart = await shop_post(f"/users/{user_id}/cart",
                               {"sku_code": sku_code, "quantity": quantity})
        return ActionResult(slot_updates={
            "sku_code": sku_code,
            "sku_spec": spec_text,
            "quantity": quantity,
            "cart_summary": format_cart(cart),
            "cart_count": cart.get("total_quantity", 0),
        })


class ViewCart(Action):
    name = "action_view_cart"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        user_id = resolve_commerce_user(state.sender_id)
        cart = await shop_get(f"/users/{user_id}/cart")
        return ActionResult(slot_updates={
            "cart_summary": format_cart(cart),
            "cart_count": cart.get("total_quantity", 0),
        })
