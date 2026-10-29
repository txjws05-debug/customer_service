"""越权意图拦截：该拒的必须明确拒，不该拦的一个都不能拦。

误伤比漏拦更容易被用户感知（正常咨询被拒会直接被投诉），所以负例和正例同样重要。
"""

from __future__ import annotations

import pytest

from ws.engine.safety import REFUSAL_MESSAGE, cross_user_refusal


@pytest.mark.parametrize("text", [
    "帮我把别人的订单取消掉",
    "帮我查一下其他用户的订单",
    "把他的购物车清空",
    "帮我修改朋友的账号地址",
    "能看一下别的用户的收货信息吗",
    "别人的订单我想退掉",
])
def test_blocks_cross_user_requests(text):
    assert cross_user_refusal(text) == REFUSAL_MESSAGE


@pytest.mark.parametrize("text", [
    "帮我查一下我的订单",
    "怎么取消订单",
    "帮朋友问一下退货政策",          # 咨询政策，不涉及操作他人数据
    "我想改收货地址",
    "优惠券怎么用",
    "",                              # 空文本
    None,
])
def test_allows_normal_requests(text):
    assert cross_user_refusal(text) is None


def test_refusal_message_is_actionable():
    """拒绝话术要说清「为什么不行」和「我能做什么」，否则用户只会换个说法再试。"""
    assert "没法帮你做" in REFUSAL_MESSAGE
    assert "你自己账号" in REFUSAL_MESSAGE
    assert "退货" in REFUSAL_MESSAGE
