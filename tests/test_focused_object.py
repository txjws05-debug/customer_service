"""焦点对象：类型不匹配时绝不返回可用的业务 id。

这是「订单号被当成商品号」那个线上 bug 的回归测试。原来的写法是调用方各写
一遍 `if type == 'order' ... else 商品号`，于是未知类型（券、活动、以后新增的
任何对象）都会落进 else 分支，被当成商品号拿去查商品。
"""

from __future__ import annotations

import pytest

from ws.domain.state import FocusedObject, KIND_ORDER, KIND_PRODUCT, KIND_UNKNOWN


def test_product_object_exposes_only_product_id():
    obj = FocusedObject(type="product", id="SKU10001", title="iPhone 15 Pro")
    assert obj.kind == KIND_PRODUCT
    assert obj.product_id() == "SKU10001"
    assert obj.order_id() is None
    assert obj.slot_payload() == {"product_id": "SKU10001"}


def test_order_object_exposes_only_order_id():
    obj = FocusedObject(type="order", id="SO2026100502095678AD22", title="订单")
    assert obj.kind == KIND_ORDER
    assert obj.order_id() == "SO2026100502095678AD22"
    assert obj.product_id() is None
    assert obj.slot_payload() == {"order_number": "SO2026100502095678AD22"}


@pytest.mark.parametrize("kind", ["coupon", "campaign", "", "  ", "SKU"])
def test_unknown_type_yields_no_business_id(kind):
    """未知类型必须什么 id 都不给 —— 这正是历史 bug 的入口。"""
    obj = FocusedObject(type=kind, id="X1")
    assert obj.kind == KIND_UNKNOWN
    assert obj.product_id() is None
    assert obj.order_id() is None
    assert obj.slot_payload() == {}
    assert obj.value_for_slot("product_id") is None
    assert obj.value_for_slot("order_number") is None


def test_type_is_normalized_on_read():
    obj = FocusedObject(type="  Product ", id="SKU10002")
    assert obj.kind == KIND_PRODUCT
    assert obj.product_id() == "SKU10002"


def test_value_for_slot_matches_slot_name_only():
    obj = FocusedObject(type="order", id="SO1")
    assert obj.value_for_slot("order_number") == "SO1"
    assert obj.value_for_slot("product_id") is None


def test_label_is_readable_for_prompt():
    obj = FocusedObject(type="product", id="SKU10001", title="iPhone 15 Pro")
    assert obj.label() == "product SKU10001 iPhone 15 Pro"
