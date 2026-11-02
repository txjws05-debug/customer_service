# -*- coding: utf-8 -*-
"""取消任务时的边界：没有活跃任务不能崩。

评测里 T67「我要买这个」→「算了不买了」稳定 500，
AttributeError: 'NoneType' object has no attribute 'task_id'。
用户改主意是最常见的对话行为之一，这里崩掉等于把最普通的场景做成故障。
"""
import pytest

from ws.domain.state import TaskState
from ws.domain.state import TaskInstance


def test_cancel_without_active_raises_value_error():
    """没有活跃任务时，cancel 抛 ValueError（业务语义），而不是 AttributeError。"""
    ts = TaskState()
    with pytest.raises(ValueError):
        ts.cancel("no-such-task")


def test_cancel_after_active_cleared():
    """取消过一次之后再取消，不能因为 active 变 None 而崩。"""
    ts = TaskState()
    ts.active = TaskInstance(flow_id="place_order", step_id="start")
    tid = ts.active.task_id
    ev = ts.cancel(tid)
    assert ev is not None
    assert ts.active is None
    # 第二次取消同一个 id：应抛 ValueError，不能 AttributeError
    with pytest.raises(ValueError):
        ts.cancel(tid)


def test_cancel_paused_task():
    """active 为 None 但 paused 里有时，仍要能取消暂停的任务。"""
    ts = TaskState()
    first = TaskInstance(flow_id="place_order", step_id="start")
    ts.active = first
    second = TaskInstance(flow_id="cart_add", step_id="start")
    ts.start(second)          # first 被挤到 paused
    ev = ts.cancel(first.task_id)
    assert ev is not None
    assert all(t.task_id != first.task_id for t in ts.paused)
