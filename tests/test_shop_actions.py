"""交易类 action 与对话流程的测试。

两类关注点：
1. **结构校验**（最容易踩、也最难在运行前发现）：流程 YAML 里引用的 action 是否
   都已注册、collect 的槽位是否都在 slots 段声明、模板里 {{ slots.x }} 是否存在、
   next 指向的步骤是否存在。这些错了会在运行时才炸，所以在这里钉死。
2. **行为校验**：用 httpx.MockTransport 假装电商中台，断言 action 打出的
   URL / 请求体正确、返回值正确写回槽位、中台的业务错误原样转达给用户。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re

import httpx
import pytest

from ws.domain.state import DialogueState, FocusedObject, TaskInstance
from ws.task.action.base import ActionCall
from ws.task.action.builder import register_service_action
from ws.task.action.registry import ActionRegistry
from ws.task.action.runner import ActionRunner
from ws.task.flow.loader import FlowLoader
from ws.task.flow.steps import ActionFlowStep, CollectSlotStep
from ws.utils import http as http_module
from ws.utils.errors import ChatServiceError
from ws.utils.shop_client import parse_quantity, resolve_commerce_user

FLOW_FILE = pathlib.Path(__file__).parents[1] / "ws" / "config" / "user_flows.yml"
TRADE_FLOWS = [
    "cart_add", "cart_view", "place_order", "buy_now", "pay_order",
    "order_list", "confirm_receipt", "my_benefits", "after_sale_request",
    "product_search",
]


# ============================================================ 工具
def _load_catalog():
    try:
        return FlowLoader().load(FLOW_FILE)
    except KeyError as exc:
        pytest.fail(f"流程 YAML 收集了未在 slots 段声明的槽位：{exc}")


def _registry() -> ActionRegistry:
    registry = ActionRegistry()
    register_service_action(registry)
    return registry


def _state(sender_id: str = "u1002", slots: dict | None = None,
           focused: FocusedObject | None = None) -> DialogueState:
    state = DialogueState(sender_id=sender_id)
    state.share.focuse_object = focused
    state.tasks.active = TaskInstance(
        flow_id="cart_add", step_id="add_to_cart", slots=dict(slots or {}))
    return state


def _run(action_name: str, state: DialogueState, **kwargs):
    runner = ActionRunner(_registry())
    return asyncio.run(runner.run(ActionCall(action_name, kwargs), state))


@pytest.fixture()
def commerce(monkeypatch):
    """假电商中台：按 (METHOD, path) 预置响应，并记录所有请求。"""
    recorder: dict = {"requests": [], "routes": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        recorder["requests"].append({
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.url.params),
            "json": json.loads(request.content) if request.content else None,
        })
        route = recorder["routes"].get((request.method, request.url.path))
        if route is None:
            return httpx.Response(404, json={
                "code": 404, "message": f"测试未预置路由 {request.method} {request.url.path}",
                "data": None})
        status, payload = route
        return httpx.Response(status, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(http_module, "http_client", client)
    yield recorder
    asyncio.run(client.aclose())


def _ok(data):
    return 200, {"code": 0, "message": "ok", "data": data}


# ============================================================ 结构校验
def test_trade_flows_exist_in_catalog():
    catalog = _load_catalog()
    missing = [flow for flow in TRADE_FLOWS if flow not in catalog.flows]
    assert not missing, f"缺少交易流程：{missing}"


def test_every_action_step_references_a_registered_action():
    catalog = _load_catalog()
    registry = _registry()
    problems = []
    for flow_id, flow in catalog.flows.items():
        for step in flow.steps:
            if isinstance(step, ActionFlowStep):
                try:
                    registry.get_action(step.action)
                except KeyError:
                    problems.append(f"{flow_id}.{step.id} 引用了未注册的 action：{step.action}")
    assert not problems, "\n".join(problems)


def test_collect_steps_only_use_declared_slots():
    catalog = _load_catalog()
    problems = []
    for flow_id, flow in catalog.flows.items():
        for step in flow.steps:
            if isinstance(step, CollectSlotStep) and step.solt_name not in catalog.slots:
                problems.append(f"{flow_id}.{step.id} 收集了未声明的槽位：{step.solt_name}")
    assert not problems, "\n".join(problems)


def test_templates_only_reference_declared_slots():
    catalog = _load_catalog()
    pattern = re.compile(r"slots\.([A-Za-z_][A-Za-z0-9_]*)")
    problems = []
    for flow_id, flow in catalog.flows.items():
        for step in flow.steps:
            text = getattr(getattr(step, "template", None), "text", "") or ""
            for name in pattern.findall(text):
                if name not in catalog.slots:
                    problems.append(f"{flow_id}.{step.id} 模板引用了未声明的槽位：{name}")
    assert not problems, "\n".join(problems)


def test_flow_next_links_point_to_existing_steps():
    catalog = _load_catalog()
    problems = []
    for flow_id, flow in catalog.flows.items():
        step_ids = {step.id for step in flow.steps}
        for step in flow.steps:
            for link in step.next:
                if link.target not in step_ids:
                    problems.append(f"{flow_id}.{step.id} 的 next 指向不存在的步骤：{link.target}")
    assert not problems, "\n".join(problems)


def test_every_flow_ends_with_end_step():
    """流程必须有终点，否则执行器会一直推进下去（历史上靠 100 次上限兜底）。"""
    from ws.task.flow.steps import EndFlowStep

    catalog = _load_catalog()
    for flow_id, flow in catalog.flows.items():
        assert any(isinstance(step, EndFlowStep) for step in flow.steps), \
            f"{flow_id} 没有 end 步骤"


def test_flow_description_given_to_planner_contains_slot_names():
    """planner 只能看到流程描述，描述里必须带槽位名，否则它只能猜槽位名。

    这是多槽位流程（售后：订单号 + 类型 + 原因）能真正跑通的前提：
    猜错槽位名的表现是「流程反复追问同一句话」。
    """
    from ws.plan.turn_plan import _describe_flow

    catalog = _load_catalog()
    text = _describe_flow(catalog.flows["after_sale_request"])
    for slot in ("order_number", "after_sale_type", "refund_reason"):
        assert slot in text, f"流程描述里缺少槽位 {slot}：{text}"
    # 没有 collect 步的流程不需要附带槽位说明
    assert "需要收集的槽位" not in _describe_flow(catalog.flows["cart_view"])


def test_dialogue_engine_builds_with_trade_capabilities():
    """整机冒烟：流程目录、action 注册、知识提供者都能装配起来。"""
    from ws.engine.builder import build_dailogue_engine

    engine = build_dailogue_engine()
    assert engine is not None


# ============================================================ 用户映射与数量解析
def test_resolve_commerce_user():
    assert resolve_commerce_user("u1001") == "u1001"
    # 登录名不是商城号时用配置的演示账号兜底
    assert resolve_commerce_user("alice") == "u1001"
    assert resolve_commerce_user(None) == "u1001"


def test_resolve_commerce_user_without_binding(monkeypatch):
    from ws.config.config import settings
    monkeypatch.setattr(settings, "commerce_default_user_id", "")
    with pytest.raises(ChatServiceError) as exc:
        resolve_commerce_user("alice")
    assert "绑定" in str(exc.value)


def test_parse_quantity():
    assert parse_quantity("两件") == 2
    assert parse_quantity("3 个") == 3
    assert parse_quantity(5) == 5
    assert parse_quantity(None) == 1
    assert parse_quantity("随便来点") == 1
    assert parse_quantity("999") == 99      # 上限夹紧
    assert parse_quantity("0") == 1


# ============================================================ 购物车
def test_add_to_cart_picks_cheapest_available_sku_for_focused_product(commerce):
    """没有 sku_code 时自动挑规格：跳过无货的，取最便宜的。"""
    commerce["routes"][("GET", "/shop/products/SKU10001")] = _ok({
        "product_id": "SKU10001", "title": "iPhone 15 Pro",
        "skus": [
            # 更便宜但无货 —— 必须被跳过
            {"sku_code": "SKU10001-09", "spec_text": "颜色:蓝色 容量:128GB",
             "price": "6999.00", "stock": 0, "status": "在售"},
            {"sku_code": "SKU10001-02", "spec_text": "颜色:原色钛金属",
             "price": "9299.00", "stock": 8, "status": "在售"},
            {"sku_code": "SKU10001-01", "spec_text": "颜色:远峰蓝",
             "price": "8999.00", "stock": 20, "status": "在售"},
        ]})
    commerce["routes"][("POST", "/shop/users/u1002/cart")] = _ok({
        "user_id": "u1002", "total_quantity": 2, "selected_quantity": 2,
        "selected_amount": "17998.00",
        "items": [{"item_id": 1, "sku_code": "SKU10001-01", "title": "iPhone 15 Pro",
                   "spec_text": "颜色:远峰蓝", "price": "8999.00", "quantity": 2,
                   "selected": True, "available": True, "subtotal": "17998.00"}]})

    state = _state(slots={"quantity": "两件"}, focused=FocusedObject(
        type="product", id="SKU10001", title="iPhone 15 Pro"))
    result = _run("action_add_to_cart", state)

    assert commerce["requests"][1]["json"] == {"sku_code": "SKU10001-01", "quantity": 2}
    assert result.slot_updates["quantity"] == 2
    assert result.slot_updates["sku_spec"] == "颜色:远峰蓝"
    assert "已勾选 2 件" in result.slot_updates["cart_summary"]


def test_add_to_cart_uses_explicit_sku_without_lookup(commerce):
    commerce["routes"][("POST", "/shop/users/u1002/cart")] = _ok({
        "user_id": "u1002", "total_quantity": 1, "selected_quantity": 1,
        "selected_amount": "14.90", "items": []})

    state = _state(slots={"sku_code": "SKU10003-01", "sku_spec": "规格:20片装"})
    result = _run("action_add_to_cart", state)

    paths = [r["path"] for r in commerce["requests"]]
    assert "/shop/products/SKU10001" not in paths          # 没有多余的商品查询
    assert result.slot_updates["sku_code"] == "SKU10003-01"


def test_add_to_cart_without_product_asks_user(commerce):
    with pytest.raises(ChatServiceError) as exc:
        _run("action_add_to_cart", _state())
    assert "打开或选择" in str(exc.value)


def test_view_cart(commerce):
    commerce["routes"][("GET", "/shop/users/u1002/cart")] = _ok({
        "user_id": "u1002", "total_quantity": 0, "selected_quantity": 0,
        "selected_amount": "0.00", "items": []})
    result = _run("action_view_cart", _state())
    assert result.slot_updates["cart_summary"] == "购物车还是空的。"


# ============================================================ 下单与支付
def test_place_order_from_cart_applies_coupon(commerce):
    commerce["routes"][("POST", "/shop/orders")] = _ok({
        "order_id": "SO20261003001", "status": "待付款", "status_desc": "订单已创建，等待付款。",
        "goods_amount": "2999.00", "discount_amount": "299.90", "freight_amount": "0",
        "pay_amount": "2699.10", "coupon_code": "C_9OFF", "expires_in_minutes": 30})

    state = _state(sender_id="u1003", slots={"coupon_code": "C_9OFF"})
    result = _run("action_place_order", state)

    body = commerce["requests"][0]["json"]
    assert body == {"user_id": "u1003", "coupon_code": "C_9OFF"}
    assert "items" not in body                      # 购物车模式不传 items
    assert result.slot_updates["order_number"] == "SO20261003001"
    assert "30 分钟内" in result.slot_updates["order_summary"]


def test_place_order_direct_mode_sends_items(commerce):
    commerce["routes"][("POST", "/shop/orders")] = _ok({
        "order_id": "SO20261003002", "status": "待付款", "status_desc": "待付款",
        "goods_amount": "798.00", "discount_amount": "0", "freight_amount": "0",
        "pay_amount": "798.00", "expires_in_minutes": 30})

    state = _state(slots={"sku_code": "SKU10005-01", "quantity": "2"})
    result = _run("action_place_order", state, mode="direct")

    assert commerce["requests"][0]["json"]["items"] == [
        {"sku_code": "SKU10005-01", "quantity": 2}]
    assert result.slot_updates["pay_amount"] == "798.00"


def test_pay_order_writes_status_and_trade_no(commerce):
    commerce["routes"][("POST", "/shop/orders/SO1/pay")] = _ok({
        "order_id": "SO1", "trade_no": "PAY20261003000001", "channel": "wechat",
        "amount": "798.00", "status": "待发货", "status_desc": "已付款，商家备货中。",
        "paid_at": "2026-10-03T10:00:00"})

    state = _state(slots={"order_number": "SO1"})
    result = _run("action_pay_order", state)
    assert result.slot_updates["pay_status"] == "待发货"
    assert "PAY20261003000001" in result.slot_updates["order_summary"]


def test_pay_order_requires_order_number(commerce):
    with pytest.raises(ChatServiceError) as exc:
        _run("action_pay_order", _state())
    assert "订单号" in str(exc.value)


# ============================================================ 订单查询与收货
def test_list_my_orders_passes_status_filter(commerce):
    commerce["routes"][("GET", "/shop/users/u1001/orders")] = _ok({
        "user_id": "u1001", "total": 1,
        "orders": [{"order_id": "SO1", "status": "待付款", "status_desc": "等待付款",
                    "pay_amount": "798.00", "quantity": 2, "title": "美的空气炸锅 5L",
                    "created_at": "2026-10-03T10:00:00"}]})

    state = _state(sender_id="u1001", slots={"order_status": "待付款"})
    result = _run("action_list_my_orders", state)
    assert commerce["requests"][0]["query"] == {"status": "待付款"}
    assert "SO1" in result.slot_updates["order_list_summary"]


def test_confirm_receipt_reports_earned_points(commerce):
    commerce["routes"][("POST", "/shop/orders/SO1/receive")] = _ok({
        "order_id": "SO1", "status": "已完成", "status_desc": "订单已完成。",
        "earned_points": 1596, "pay_amount": "798.00"})

    state = _state(slots={"order_number": "SO1"})
    result = _run("action_confirm_receipt", state)
    assert result.slot_updates["earned_points"] == 1596
    assert "1596 积分" in result.slot_updates["order_summary"]


# ============================================================ 营销
def test_list_my_coupons_with_goods_amount_filter(commerce):
    commerce["routes"][("GET", "/shop/users/u1002/coupons")] = _ok({
        "user_id": "u1002", "total": 1, "usable_count": 0,
        "coupons": [{"id": 1, "code": "C_NEW10", "name": "新人专享 满100减10",
                     "type": "full_reduce", "threshold": "100", "amount": "10",
                     "rate": None, "status": "unused", "end_at": "2026-11-01T00:00:00",
                     "usable": False, "reason": "差 ¥85.10 元可用"}]})

    state = _state(slots={"goods_amount": "14.90"})
    result = _run("action_list_my_coupons", state)
    assert commerce["requests"][0]["query"] == {"goods_amount": "14.90"}
    assert "当前可用 0 张" in result.slot_updates["coupon_summary"]


def test_my_points(commerce):
    commerce["routes"][("GET", "/shop/users/u1002/points")] = _ok({
        "user_id": "u1002", "nickname": "王敏", "level": "普通会员", "is_plus": False,
        "points": 149, "growth": 149, "next_level_points": 851, "ledger": []})
    result = _run("action_my_points", _state())
    assert result.slot_updates["points"] == 149
    assert "851" in result.slot_updates["points_summary"]


# ============================================================ 售后
@pytest.mark.parametrize("raw,expected", [
    ("退货退款", "return_refund"),
    ("我要退货", "return_refund"),
    ("仅退款", "refund_only"),
    ("只退款不退货", "refund_only"),
    ("refund_only", "refund_only"),
    ("return_refund", "return_refund"),
    ("随便", "refund_only"),          # 拿不准时选代价最小的
])
def test_after_sale_type_normalization(raw, expected):
    from ws.task.custom.shop_after_sale import normalize_after_sale_type
    assert normalize_after_sale_type(raw) == expected


def test_apply_after_sale(commerce):
    commerce["routes"][("POST", "/shop/orders/SO1/after-sales")] = _ok({
        "ticket_no": "AS20261003001", "order_id": "SO1", "type": "return_refund",
        "type_desc": "退货退款", "status": "submitted", "status_desc": "售后申请已提交，等待审核。",
        "reason": "尺码不合适", "evidence": [], "refund_amount": "798.00",
        "remark": None, "created_at": "2026-10-03T10:00:00",
        "updated_at": "2026-10-03T10:00:00", "can_cancel": True, "can_return": False})

    state = _state(slots={"order_number": "SO1", "after_sale_type": "我要退货",
                          "refund_reason": "尺码不合适"})
    result = _run("action_apply_after_sale", state)

    assert commerce["requests"][0]["json"]["type"] == "return_refund"
    assert commerce["requests"][0]["json"]["reason"] == "尺码不合适"
    assert result.slot_updates["after_sale_no"] == "AS20261003001"


def test_apply_after_sale_requires_reason(commerce):
    with pytest.raises(ChatServiceError) as exc:
        _run("action_apply_after_sale", _state(slots={"order_number": "SO1"}))
    assert "原因" in str(exc.value)


# ============================================================ 搜索
def test_search_products_builds_query(commerce):
    commerce["routes"][("GET", "/shop/products")] = _ok({
        "total": 1, "page": 1, "page_size": 5, "keyword": "水壶",
        "items": [{"product_id": "SKU10002", "title": "小米恒温电热水壶 3",
                   "price": "149.00", "cover_url": None, "category": "厨房家电",
                   "brand": "小米", "stock_status": "有货", "rating_avg": "4.00",
                   "rating_count": 1, "sales_count": 2}]})

    state = _state(slots={"keyword": "水壶", "max_price": "200", "sort": "price_asc"})
    result = _run("action_search_products", state)

    query = commerce["requests"][0]["query"]
    assert query["q"] == "水壶"
    assert query["max_price"] == "200"
    assert query["sort"] == "price_asc"
    assert "小米恒温电热水壶" in result.slot_updates["search_summary"]


# ============================================================ 错误透传
def test_business_error_is_forwarded_to_user(commerce):
    """中台的业务失败（库存不足等）必须原样告诉用户，而不是「服务不可用」。"""
    commerce["routes"][("POST", "/shop/orders")] = (
        409, {"code": 409, "message": "「美的空气炸锅 5L」库存不足（仅剩 3 件）。", "data": None})

    with pytest.raises(ChatServiceError) as exc:
        _run("action_place_order", _state())
    assert "库存不足" in str(exc.value)


def test_legacy_detail_error_is_forwarded(commerce):
    """老接口用的是 FastAPI 的 detail 字段，也要能透传。"""
    commerce["routes"][("GET", "/shop/users/u1002/cart")] = (
        404, {"detail": "用户 u1002 不存在。"})
    with pytest.raises(ChatServiceError) as exc:
        _run("action_view_cart", _state())
    assert "不存在" in str(exc.value)
