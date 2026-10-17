"""闲聊缓存命中时也要「流」着出，而不是整段蹦出来。

修过的 bug（用户可见）：闲聊回答有缓存，命中时 `yield cached` 一次吐完整段，
前端表现就是**一股脑出现**；而知识问答没有这样一次吐，于是出现
「闲聊不流、知识流」的诡异现象 —— 用户会以为流式功能坏了。

缓存命中的正确语义是「省掉 LLM 调用」，不是「省掉打字机效果」。
"""

from __future__ import annotations

import asyncio

from ws.chitchat.handler import replay_cached


def test_cached_answer_is_streamed_in_pieces():
    text = "您好呀，我是电商智能客服，可以帮您查订单、查物流、退货退款、开发票～"

    async def collect() -> list[str]:
        return [piece async for piece in replay_cached(text)]

    pieces = asyncio.run(collect())

    assert len(pieces) > 1, "缓存命中必须分成多段，否则前端就是一股脑弹出"
    assert "".join(pieces) == text, "切块不能丢字或改字"
    assert all(pieces), "不能产出空片段"


def test_replay_of_empty_text_terminates():
    """空串是合法输入（不能卡死，也不能产出空片段）。"""
    async def collect() -> list[str]:
        return [piece async for piece in replay_cached("")]

    assert asyncio.run(collect()) == []
