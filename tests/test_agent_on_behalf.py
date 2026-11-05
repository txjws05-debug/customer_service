"""客服 Agent 代用户调中台时，必须声明「替谁办事」。

中台对裸服务令牌跨用户放行；如果 Agent 处理用户对话时不带 X-On-Behalf-Of，
用户在聊天里报一个别人的订单号，Agent 就会拿特权身份把别人的订单查出来。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ws.domain.message import MessageType, ProcessResult, UserMessage
from ws.service.dialogue_service import DialogueService
from ws.utils import http as http_module

ORDER_URL = "http://ecommerce/orders/B20260409001/status"


@pytest.fixture()
def seen(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"status": "x"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(http_module, "http_client", client)
    yield requests
    asyncio.run(client.aclose())


class _Repo:
    async def load(self, sender_id):
        return object()

    async def save(self, state):
        return None


class _Engine:
    """引擎里任意一处调中台，都应带上当前用户身份。"""

    async def process_message(self, state, message):
        await http_module.get_api_data(ORDER_URL)
        return ProcessResult(sender_id=message.sender_id,
                             message_id=message.message_id, messages=[])

    async def process_message_stream(self, state, message):
        await http_module.get_api_data(ORDER_URL)
        yield "ok"


def _service() -> DialogueService:
    return DialogueService(dialogue_repository=_Repo(), dialogue_engine=_Engine())


def _msg(sender: str, cuid: str | None = "same") -> UserMessage:
    """cuid 默认与 sender 同名（这些用例里账号已绑定同名商城号）；None = 未绑定。"""
    return UserMessage(sender_id=sender, message_id="m1",
                       type=MessageType.TEXT, text="查一下 B20260409001",
                       commerce_user_id=sender if cuid == "same" else cuid)


def test_dialogue_calls_declare_the_user(seen):
    asyncio.run(_service().process_message(_msg("u1002")))
    assert seen[0].headers.get("x-on-behalf-of") == "u1002"


def test_stream_dialogue_calls_declare_the_user(seen):
    async def consume():
        return [d async for d in _service().process_message_stream(_msg("u1003"))]

    asyncio.run(consume())
    assert seen[0].headers.get("x-on-behalf-of") == "u1003"


def test_unbound_user_fails_closed(seen):
    """查不到商城号：仍要带头（空值），让中台拒绝，而不是按特权身份放行。"""
    asyncio.run(_service().process_message(_msg("alice", cuid=None)))
    assert "x-on-behalf-of" in seen[0].headers
    assert seen[0].headers["x-on-behalf-of"] == ""


def test_identity_does_not_leak_after_dialogue(seen):
    asyncio.run(_service().process_message(_msg("u1002")))
    asyncio.run(http_module.get_api_data(ORDER_URL))
    assert "x-on-behalf-of" not in seen[1].headers


def test_stream_behind_first_token_guard_declares_the_user(seen):
    """线上流式接口会先套一层首包超时，身份不能在这一层丢掉。"""
    from ws.utils.stream_guard import guard_first_token

    async def consume():
        stream = guard_first_token(
            _service().process_message_stream(_msg("u1003")), deadline=5)
        return [d async for d in stream]

    asyncio.run(consume())
    assert seen[0].headers.get("x-on-behalf-of") == "u1003"
