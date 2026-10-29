"""人工接管：触发条件、幂等建单、状态流转。

用假仓储测服务层，不连库 —— 状态机是这段代码最容易写错的地方，
必须能在毫秒级跑完整条路径。
"""

from __future__ import annotations

import asyncio

from ws.service.handoff_service import (
    HANDOFF_REPLY,
    WAITING_REPLY,
    HandoffService,
    wants_human,
)


class FakeRepo:
    def __init__(self):
        self.tickets = {}
        self.created = 0
        self.touched = []

    async def get_open(self, sender_id):
        for ticket in self.tickets.values():
            if ticket["sender_id"] == sender_id and ticket["status"] in ("pending", "taken"):
                return type("T", (), ticket)
        return None

    async def create(self, sender_id, reason, last_message=None):
        self.created += 1
        tid = f"t{self.created}"
        self.tickets[tid] = {"id": tid, "sender_id": sender_id, "status": "pending",
                             "reason": reason, "last_message": last_message}
        return type("T", (), self.tickets[tid])

    async def touch(self, sender_id, last_message=None):
        self.touched.append((sender_id, last_message))


def _run(coro):
    return asyncio.run(coro)


def test_wants_human_matches_common_phrasings():
    for text in ("我要转人工", "转人工", "帮我找人工客服", "真人客服在吗"):
        assert wants_human(text), text


def test_wants_human_is_deliberately_loose():
    """规则刻意放宽：误转的代价是一个人看一眼，漏转的代价是用户困在机器人里。

    所以「人工客服几点上班」这种本来只是问营业时间的消息也会转人工。
    这是有意为之，不是 bug —— 如果哪天要收紧，得先想清楚用什么信号补上漏转。
    """
    assert wants_human("人工客服几点上班")

    for text in (None, "", "退货怎么办", "这个多少钱"):
        assert not wants_human(text), text


def test_first_request_creates_ticket_and_replies():
    repo = FakeRepo()
    service = HandoffService(lambda: repo)
    reply = _run(service.intercept("u1", "我要转人工"))
    assert reply == HANDOFF_REPLY
    assert repo.created == 1


def test_repeated_request_does_not_create_duplicates():
    repo = FakeRepo()
    service = HandoffService(lambda: repo)
    _run(service.intercept("u1", "转人工"))
    reply = _run(service.intercept("u1", "转人工"))
    assert reply == WAITING_REPLY, "已有工单时应回「正在查看」而不是再建一张"
    assert repo.created == 1


def test_open_ticket_swallows_follow_up_messages():
    """有未结束工单时，后续消息不再进 AI —— 否则用户会同时收到两套回答。"""
    repo = FakeRepo()
    service = HandoffService(lambda: repo)
    _run(service.intercept("u1", "转人工"))
    reply = _run(service.intercept("u1", "我的订单还没发货"))
    assert reply == WAITING_REPLY
    assert repo.touched == [("u1", "我的订单还没发货")]


def test_unrelated_user_still_goes_to_ai():
    repo = FakeRepo()
    service = HandoffService(lambda: repo)
    assert _run(service.intercept("u2", "这个多少钱")) is None
