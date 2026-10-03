#!/usr/bin/env python3
"""客服 Agent ↔ 电商中台 的端到端联调脚本（打真实服务，不用 mock）。

单测里的 MockTransport 能验证「我们发了什么」，但验证不了「服务是否真的认这个
路径和请求体」。这个脚本按一条真实客户路径跑一遍：

    加购 → 看购物车 → 查券 → 下单（用券）→ 未发货时收货（应被拒）
         → 支付 → 运营端发货并推进 → 确认收货（得积分）→ 查积分
         → 申请售后 → 看订单列表 → 搜索商品

用法（先让中台和 PostgreSQL 跑起来）：

    # 1) 起库
    docker run -d --name cs-e2e-pg -e POSTGRES_PASSWORD=test -e POSTGRES_USER=cs \
        -e POSTGRES_DB=commerce -p 55434:5432 postgres:16

    # 2) 起中台（会用 SEED_ON_STARTUP 自动建表并灌演示数据）
    cd ecommerce-service-backend
    DATABASE_URL=postgresql+psycopg2://cs:test@127.0.0.1:55434/commerce \
        APP_PORT=18091 uv run --locked python main.py

    # 3) 跑本脚本
    COMMERCE_API_BASE_URL=http://127.0.0.1:18091 \
        LLM_API_KEY=x LLM_MODEL=x LLM_BASE_URL=http://x \
        DATABASE_URL=postgresql+asyncpg://u:p@127.0.0.1:5432/d \
        APP_HOST=0.0.0.0 APP_PORT=18082 \
        python scripts/e2e_shop_flow.py

注意：脚本会真的在中台里创建订单、扣库存、发券核销，因此只对演示库运行。
"""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx

from ws.config.config import settings
from ws.domain.state import DialogueState, FocusedObject, TaskInstance
from ws.task.action.base import ActionCall
from ws.task.action.builder import register_service_action
from ws.task.action.registry import ActionRegistry
from ws.task.action.runner import ActionRunner
from ws.utils import http as http_module
from ws.utils.errors import ChatServiceError


def make_state(sender: str, **slots) -> DialogueState:
    state = DialogueState(sender_id=sender)
    state.tasks.active = TaskInstance(flow_id="e2e", step_id="step", slots=dict(slots))
    return state


def show(title: str, text: str) -> None:
    print(f"\n【{title}】\n{text}")


async def main(base_url: str, user: str) -> None:
    http_module.init_http_client()
    registry = ActionRegistry()
    register_service_action(registry)
    runner = ActionRunner(registry)

    async def run(action: str, state: DialogueState, **kwargs):
        return await runner.run(ActionCall(action, kwargs), state)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            health = await client.get(f"{base_url}/health")
            assert health.status_code == 200, f"中台不可用：{health.status_code}"
            print(f"中台健康检查通过：{base_url}")

            # 先清空购物车：否则反复跑脚本时加购会累加，金额断言就对不上了
            cart = (await client.get(f"{base_url}/shop/users/{user}/cart")).json()["data"]
            for item in cart["items"]:
                await client.delete(
                    f"{base_url}/shop/users/{user}/cart/{item['item_id']}")
            print(f"购物车已清空（原有 {cart['total_quantity']} 件）")

        # 1) 加购：聚焦商品 + 口语数量，规格由系统自动挑
        state = make_state(user, quantity="两件")
        state.share.focuse_object = FocusedObject(
            type="product", id="SKU10005", title="美的空气炸锅 5L")
        result = await run("action_add_to_cart", state)
        show("加购", result.slot_updates["cart_summary"])
        assert result.slot_updates["quantity"] == 2

        result = await run("action_view_cart", make_state(user))
        show("购物车", result.slot_updates["cart_summary"])

        result = await run("action_list_my_coupons", make_state(user, goods_amount="798"))
        show("我的优惠券", result.slot_updates["coupon_summary"])

        # 动态挑一张当前可用的券：不同用户名下的券不一样，写死券码会让脚本只对
        # 某个演示账号有效（真实踩过：换个用户就报「未找到优惠券」）
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url}/shop/users/{user}/coupons",
                                    params={"goods_amount": "798"})
            assert resp.status_code == 200, resp.text
            usable = [c for c in resp.json()["data"]["coupons"] if c["usable"]]
        coupon_code = usable[0]["code"] if usable else None
        print(f"本次下单将使用优惠券：{coupon_code or '（无可用券）'}")

        # 2) 下单
        order_slots = {"goods_amount": "798"}
        if coupon_code:
            order_slots["coupon_code"] = coupon_code
        result = await run("action_place_order", make_state(user, **order_slots))
        order_number = result.slot_updates["order_number"]
        show("下单", result.slot_updates["order_summary"])
        assert float(result.slot_updates["pay_amount"]) <= 798.0

        # 3) 未发货就确认收货，必须被中台拒绝并把原因原样告诉用户
        try:
            await run("action_confirm_receipt", make_state(user, order_number=order_number))
            raise AssertionError("未发货的订单竟然能确认收货")
        except ChatServiceError as exc:
            show("拦截（预期）", str(exc))

        result = await run("action_pay_order",
                           make_state(user, order_number=order_number, pay_channel="alipay"))
        show("支付", result.slot_updates["order_summary"])

        # 4) 运营端发货并推进履约（走真实管理端接口）
        async with httpx.AsyncClient(timeout=10) as client:
            for path, body in (
                (f"/shop/admin/orders/{order_number}/ship", {"company": "顺丰速运"}),
                (f"/shop/admin/orders/{order_number}/advance", {}),
                (f"/shop/admin/orders/{order_number}/advance", {}),
            ):
                response = await client.post(f"{base_url}{path}", json=body)
                assert response.status_code == 200, response.text
            show("运营端发货并推进", response.json()["data"]["status"])

        result = await run("action_confirm_receipt",
                           make_state(user, order_number=order_number))
        show("确认收货", result.slot_updates["order_summary"])
        assert result.slot_updates["earned_points"] > 0

        result = await run("action_my_points", make_state(user))
        show("我的积分", result.slot_updates["points_summary"])

        # 5) 售后：口语说法要能归一化成退货退款
        state = make_state(user, order_number=order_number,
                           after_sale_type="我要退货", refund_reason="用了一次不想要了")
        result = await run("action_apply_after_sale", state)
        show("申请售后", result.slot_updates["after_sale_summary"])
        assert result.slot_updates["after_sale_type"] == "return_refund"

        result = await run("action_list_my_orders", make_state(user))
        show("我的订单", result.slot_updates["order_list_summary"])

        result = await run("action_search_products", make_state(user, keyword="水壶"))
        show("搜索水壶", result.slot_updates["search_summary"])

        print("\n===== 端到端链路全部通过 =====")
    finally:
        await http_module.close_http_client()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="客服 Agent 与电商中台的端到端联调")
    parser.add_argument("--base-url", default=settings.commerce_api_base_url)
    parser.add_argument("--user", default=os.getenv("COMMERCE_USER", "u1002"))
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.user))
