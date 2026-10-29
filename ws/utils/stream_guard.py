"""流式的首包超时。

为什么需要：流式接口的「慢」和普通接口不一样 —— 只要首包迟迟不来，用户看到的就是
一个空白页面，没有任何反馈。等满 LLM 的 8s 超时再报错，体验上等于卡死。

做法：只对**第一个 chunk** 设 deadline，拿到首包之后就不再计时
（长回答本来就该慢慢出，不能中途砍断）。

放在 HTTP 层包一次，而不是改 5 处 `chain.astream`：链式调用散在
chitchat / clarify / knowledge / task 四处，逐个改容易漏，也容易把
「非 LLM 的流」（比如缓存的闲聊）误伤。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

FIRST_TOKEN_FALLBACK = (
    "抱歉，这次响应有点慢，我先不耽误你了。可以稍后再问一次，"
    "或者直接说「转人工」，我帮你接人工客服。"
)


async def guard_first_token(stream: AsyncIterator[str], *, deadline: float,
                            fallback_text: str = FIRST_TOKEN_FALLBACK,
                            on_timeout=None) -> AsyncIterator[str]:
    """首包超过 deadline 就放弃，改吐 fallback 文案。"""
    iterator = stream.__aiter__()
    try:
        first = await asyncio.wait_for(iterator.__anext__(), timeout=deadline)
    except asyncio.TimeoutError:
        if on_timeout is not None:
            on_timeout()
        yield fallback_text
        return
    except StopAsyncIteration:
        return
    yield first
    async for chunk in iterator:
        yield chunk
