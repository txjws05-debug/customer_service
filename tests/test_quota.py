"""限流与 token 预算：边界必须可算，不能靠"感觉"。

用假时钟测，不 sleep —— 靠真实等待的测试在 CI 上就是随机失败源。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ws.guard.quota import (
    SlidingWindowLimiter,
    TokenBudget,
    UsageTracker,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ------------------------------------------------------------------ 限流
def test_limiter_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock)

    for _ in range(3):
        assert limiter.hit("u1").allowed

    blocked = limiter.hit("u1")
    assert not blocked.allowed
    assert blocked.retry_after > 0
    assert "每分钟最多 3 条" in blocked.reason


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("u1").allowed
    assert limiter.hit("u1").allowed
    assert not limiter.hit("u1").allowed

    clock.advance(61)
    assert limiter.hit("u1").allowed, "窗口滑过去后应恢复"


def test_limiter_is_per_user():
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("u1").allowed
    assert not limiter.hit("u1").allowed
    assert limiter.hit("u2").allowed, "别人的额度不能被 u1 吃掉"


# ------------------------------------------------------------------ 预算
def test_budget_accumulates_and_blocks():
    clock = FakeClock(86_400 * 20)  # 固定到某一天
    budget = TokenBudget(limit=100, clock=clock)
    assert not budget.exhausted()
    budget.spend(60)
    assert budget.used == 60
    assert not budget.exhausted()
    budget.spend(50)
    assert budget.exhausted(), "超过上限即视为用尽"


def test_budget_resets_next_day():
    clock = FakeClock(86_400 * 20 + 1000)
    budget = TokenBudget(limit=100, clock=clock)
    budget.spend(100)
    assert budget.exhausted()

    clock.advance(86_400)
    assert not budget.exhausted(), "跨天应自动归零"
    assert budget.used == 0


def test_budget_zero_means_unlimited():
    budget = TokenBudget(limit=0, clock=FakeClock())
    budget.spend(10**9)
    assert not budget.exhausted()


# ------------------------------------------------------- 用量回调
def _fake_response(text: str | None = None, total_tokens: int | None = None):
    message = SimpleNamespace(usage_metadata={"total_tokens": total_tokens} if total_tokens else None)
    generation = SimpleNamespace(text=text or "", message=message)
    return SimpleNamespace(generations=[[generation]])


def test_usage_tracker_prefers_reported_tokens(monkeypatch):
    from ws.guard import quota

    recorded = []
    monkeypatch.setattr(quota, "add_tokens", recorded.append)
    UsageTracker().on_llm_end(_fake_response("短", total_tokens=321))
    assert recorded == [321]


def test_usage_tracker_falls_back_to_length(monkeypatch):
    from ws.guard import quota

    recorded = []
    monkeypatch.setattr(quota, "add_tokens", recorded.append)
    UsageTracker().on_llm_end(_fake_response("一二三四五六七八九十"))  # 10 字符
    assert recorded == [5]


def test_usage_tracker_survives_broken_response(monkeypatch):
    """LLM 回调里抛异常会污染主流程，所以畸形响应必须被吞掉。"""
    from ws.guard import quota

    recorded = []
    monkeypatch.setattr(quota, "add_tokens", recorded.append)
    UsageTracker().on_llm_end(SimpleNamespace(generations=[]))
    assert recorded == []


# ------------------------------------------------------- 组合行为
def test_acquire_chat_reports_budget_before_rate_limit(monkeypatch):
    from ws.guard import quota

    monkeypatch.setattr(quota._budget, "_limit", 10)
    monkeypatch.setattr(quota._budget, "_used", 10)
    decision = quota.acquire_chat("u1")
    assert not decision.allowed
    assert "额度" in decision.reason
    quota._budget.reset()


@pytest.fixture(autouse=True)
def _reset_global_state():
    from ws.guard import quota

    quota._limiter.reset()
    quota._budget.reset()
    yield
    quota._limiter.reset()
    quota._budget.reset()
