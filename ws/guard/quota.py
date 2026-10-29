"""对话配额：按用户限流 + 全站每日 token 预算。

为什么需要这一层：
- 一个脚本循环打 `/api/chat`，几分钟就能把 LLM 额度烧光，同时把 2C2G 的机器打满
  （每次对话 = 一次 LLM 调用 + 一次向量检索 + 一次中台请求）；
- 就算每个用户都守规矩，全站也要有一条兜底线：模型按 token 计费，
  「跑飞」这件事只能靠预算拦住，不能靠自觉。

为什么是进程内实现：当前单实例部署，进程内滑窗足够且零依赖。
将来多实例时把 `_SlidingWindow` 换成 Redis 实现即可，对外只保留
`acquire_chat()` / `add_tokens()` 两个入口，调用方不用改。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

from langchain_core.callbacks import BaseCallbackHandler

from ws import metrics
from ws.config.config import settings

logger = logging.getLogger("ws.quota")


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str = ""
    retry_after: int = 0


class SlidingWindowLimiter:
    """滑动窗口计数：只保留窗口内的时间戳，避免固定窗口的边界突刺。"""

    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self._limit = max(1, limit)
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> QuotaDecision:
        now = self._clock()
        bucket = self._hits.setdefault(key, deque())
        while bucket and now - bucket[0] >= self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            wait = int(self._window - (now - bucket[0])) + 1
            return QuotaDecision(
                allowed=False,
                reason=(f"你问得有点快，请等 {wait} 秒再试。"
                        f"（每分钟最多 {self._limit} 条）"),
                retry_after=wait,
            )
        bucket.append(now)
        return QuotaDecision(allowed=True)

    def reset(self) -> None:
        self._hits.clear()


class TokenBudget:
    """按自然日累计的 token 预算；跨天自动归零。"""

    def __init__(self, limit: int, clock=time.time):
        self._limit = max(0, limit)
        self._clock = clock
        self._day = int(self._clock() // 86400)
        self._used = 0

    def _roll(self) -> None:
        today = int(self._clock() // 86400)
        if today != self._day:
            self._day = today
            self._used = 0

    def spend(self, tokens: int) -> None:
        if tokens <= 0:
            return
        self._roll()
        self._used += tokens

    @property
    def used(self) -> int:
        self._roll()
        return self._used

    @property
    def limit(self) -> int:
        return self._limit

    def exhausted(self) -> bool:
        self._roll()
        return self._limit > 0 and self._used >= self._limit

    def reset(self) -> None:
        self._used = 0


_limiter = SlidingWindowLimiter(settings.chat_rate_limit_per_minute)
_budget = TokenBudget(settings.chat_daily_token_budget)


def acquire_chat(user: str) -> QuotaDecision:
    """对话前调用：先看全站预算，再看用户频率。"""
    if _budget.exhausted():
        metrics.inc("chat_budget_exceeded_total")
        logger.warning("日 token 预算已用尽：%d/%d", _budget.used, _budget.limit)
        return QuotaDecision(
            allowed=False,
            reason="今天的智能问答额度已经用完了，请明天再来，或直接联系人工客服。",
        )

    decision = _limiter.hit(user or "anonymous")
    if not decision.allowed:
        metrics.inc("chat_rate_limited_total", {"user": user or "anonymous"})
    return decision


def add_tokens(tokens: int) -> None:
    _budget.spend(tokens)
    # 预算用量必须以指标形式暴露：它是进程内状态，外部（包括探测脚本、
    # 监控、另一个进程）看不到内存，只能通过 /metrics 读
    metrics.set_gauge("chat_budget_used", float(_budget.used))
    metrics.set_gauge("chat_budget_limit", float(_budget.limit))


def budget_status() -> dict:
    return {"used": _budget.used, "limit": _budget.limit}


class UsageTracker(BaseCallbackHandler):
    """把每次 LLM 调用的 token 消耗记进预算。

    挂在 llm 单例上（见 ws/utils/llm_client.py），因此 13 个调用点一处不漏。
    拿不到 usage_metadata 时按字符数估算（中文约 2 字符/token），
    宁可高估也不低估 —— 预算是保险丝，不是账单。
    """

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        tokens = 0
        try:
            generation = response.generations[0][0]
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if usage:
                tokens = int(usage.get("total_tokens") or 0)
            if not tokens:
                text = getattr(generation, "text", "") or ""
                tokens = max(1, len(text) // 2)
        except (AttributeError, IndexError, TypeError, ValueError):
            tokens = 0
        if tokens:
            add_tokens(tokens)


def _reset_for_tests() -> None:
    _limiter.reset()
    _budget.reset()
    metrics.set_gauge("chat_budget_used", 0.0)
