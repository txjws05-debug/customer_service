"""意图解析失败该当「正常回复」，不是 HTTP 错误。

排查来历：评测里 T07「还没发货，能改收货地址吗」偶发 400，原始回复为空。
查下来是规划器连试两次仍拿不到合法 JSON，于是抛了 `ChatServiceError` ——
路由层把 ChatServiceError 一律映射成 400，可这句
「我没太理解您的意思，能换个说法再描述一次吗？」本来就是个正常回答。

后果不只是评测变红：前端会弹错误提示，用户以为系统坏了，
而实际上系统只是没听懂。所以用一个独立异常类型把它和真故障分开。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ws.domain.message import MessageType, UserMessage
from ws.engine.dialogue_engine import DialogueEngine
from ws.plan.models import PlanUnavailable
from ws.utils.errors import ChatServiceError

REPLY = "我没太理解您的意思，能换个说法再描述一次吗？"


def _engine(planner) -> DialogueEngine:
    """只测「规划失败」这一条路径，其余依赖用哑对象占位。"""
    return DialogueEngine(
        turn_plan=planner,
        turn_plan_validation=SimpleNamespace(),
        task_handler=SimpleNamespace(_flow_catalog={}),
        knowledge_handler=SimpleNamespace(knowledge_intents={}),
        chitchat_handler=SimpleNamespace(),
        clarify_responder=SimpleNamespace(),
    )


def _message() -> UserMessage:
    return UserMessage(sender_id="u-test", message_id="m-1",
                       type=MessageType.TEXT, text="还没发货，能改收货地址吗")


class _FailingPlanner:
    async def plan(self, **kwargs):
        raise PlanUnavailable(REPLY)


def test_plan_unavailable_is_not_a_service_error():
    """必须是两种类型：否则路由层会继续把它映射成 400。"""
    assert not issubclass(PlanUnavailable, ChatServiceError)


def test_engine_returns_normal_message_when_plan_fails():
    engine = _engine(_FailingPlanner())
    messages = asyncio.run(engine._execute_text_message(_message(), SimpleNamespace()))
    assert len(messages) == 1
    assert messages[0].text == REPLY


def test_stream_path_also_yields_the_reply():
    """流式与非流式是两条独立路径，只修一条等于没修。"""
    engine = _engine(_FailingPlanner())

    async def collect():
        return [chunk async for chunk in engine._stream_text(_message(), SimpleNamespace())]

    assert asyncio.run(collect()) == [REPLY]


def test_reply_is_actionable():
    """话术要给出「下一步怎么做」，否则用户只会重复同一句话。"""
    assert "换个说法" in REPLY or "再描述" in REPLY
