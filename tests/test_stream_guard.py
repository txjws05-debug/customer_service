"""流式首包超时：慢就降级，快就原样透传。

这个守卫的价值全在边界上：首包 5.9s 要放行、6.1s 要降级、
首包之后的慢（长回答）不能被砍断。
"""

from __future__ import annotations

import asyncio

import pytest

from ws.utils.stream_guard import FIRST_TOKEN_FALLBACK, guard_first_token


async def _collect(agen) -> list[str]:
    return [chunk async for chunk in agen]


async def _slow_first(delay: float, chunks=("a", "b")):
    await asyncio.sleep(delay)
    for chunk in chunks:
        yield chunk


async def _slow_later(chunks=("a", "b", "c"), delay=0.2):
    yield chunks[0]
    await asyncio.sleep(delay)
    for chunk in chunks[1:]:
        yield chunk


def test_fast_first_token_passes_through():
    out = asyncio.run(_collect(guard_first_token(_slow_first(0.01), deadline=0.5)))
    assert out == ["a", "b"]


def test_slow_first_token_falls_back():
    out = asyncio.run(_collect(guard_first_token(_slow_first(0.4), deadline=0.1)))
    assert out == [FIRST_TOKEN_FALLBACK]


def test_timeout_callback_fires():
    hits = []
    asyncio.run(_collect(guard_first_token(
        _slow_first(0.4), deadline=0.1, on_timeout=lambda: hits.append(1))))
    assert hits == [1]


def test_slow_body_is_not_cut():
    """首包按时到达后，后面慢不该被砍 —— 长回答本来就该慢慢出。"""
    out = asyncio.run(_collect(guard_first_token(_slow_later(delay=0.3), deadline=0.1)))
    assert out == ["a", "b", "c"]


def test_empty_stream_yields_nothing():
    async def empty():
        if False:
            yield ""

    assert asyncio.run(_collect(guard_first_token(empty(), deadline=0.2))) == []
