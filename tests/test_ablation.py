# -*- coding: utf-8 -*-
"""消融开关的行为约定。

两类断言：
1. 默认关闭时，行为与改造前完全一致（这是回归底线）；
2. 打开时，对应能力确实失效（这是实验有效性的前提）。

如果第 2 类测试失败，意味着「关掉开关后能力还在」，那么消融实验
测到的差异就不是该能力造成的 —— 结论会站不住。
"""
import pytest

from ws.config.config import settings
from ws.domain.state import FocusedObject
from ws.engine.safety import cross_user_refusal

CROSS_USER = "帮我把别人的订单取消掉"


def test_safety_on_by_default():
    """默认不消融：越权请求必须被拦截。"""
    assert settings.ablate_safety is False
    assert cross_user_refusal(CROSS_USER) is not None


def test_safety_disabled_by_switch(monkeypatch):
    """打开开关后，规则不再拦截（交给模型自由发挥）。"""
    monkeypatch.setattr(settings, "ablate_safety", True)
    assert cross_user_refusal(CROSS_USER) is None


def test_normal_request_never_blocked(monkeypatch):
    """开关打开也不能误伤正常请求（防止早退位置写错）。"""
    monkeypatch.setattr(settings, "ablate_safety", True)
    assert cross_user_refusal("帮我查一下我的订单") is None


def test_focus_typed_by_default():
    """默认不消融：商品就是商品。"""
    assert settings.ablate_focus is False
    obj = FocusedObject(type="product", id="SKU10001")
    assert obj.kind == "product"
    assert obj.product_id() == "SKU10001"


def test_focus_degraded_by_switch(monkeypatch):
    """打开开关后，焦点对象退化为未知类型，槽位不再按 kind 映射。"""
    monkeypatch.setattr(settings, "ablate_focus", True)
    obj = FocusedObject(type="product", id="SKU10001")
    assert obj.kind != "product"
    # 类型化失效的直接后果：拿不到商品槽位
    assert obj.product_id() is None
