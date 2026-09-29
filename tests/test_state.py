import pytest

from ws.domain.state import TaskInstance, TaskState
from ws.task.lifecycle.models import (
    TaskCanceled,
    TaskResumed,
    TaskStarted,
    TaskSwitched,
)


def _task(flow_id: str = "flow_a") -> TaskInstance:
    return TaskInstance(flow_id=flow_id, step_id="start")


def test_start_first_task():
    state = TaskState()
    event = state.start(_task())
    assert isinstance(event, TaskStarted)
    assert state.active is not None
    assert state.paused == []


def test_start_second_task_switches_and_pauses():
    state = TaskState()
    first = _task("flow_a")
    state.start(first)
    event = state.start(_task("flow_b"))
    assert isinstance(event, TaskSwitched)
    assert state.active.flow_id == "flow_b"
    assert len(state.paused) == 1
    assert state.paused[0].flow_id == "flow_a"


def test_cancel_active():
    state = TaskState()
    task = _task()
    state.start(task)
    event = state.cancel(task.task_id)
    assert isinstance(event, TaskCanceled)
    assert state.active is None


def test_cancel_paused():
    state = TaskState()
    first = _task("flow_a")
    state.start(first)
    state.start(_task("flow_b"))
    event = state.cancel(first.task_id)
    assert isinstance(event, TaskCanceled)
    assert state.paused == []


def test_cancel_unknown_raises():
    state = TaskState()
    state.start(_task())
    with pytest.raises(ValueError):
        state.cancel("nope")


def test_resume_paused_switches_back():
    state = TaskState()
    first = _task("flow_a")
    state.start(first)
    state.start(_task("flow_b"))
    event = state.resume(first.task_id)
    assert isinstance(event, TaskSwitched)
    assert state.active.flow_id == "flow_a"
    assert state.paused[0].flow_id == "flow_b"


def test_resume_without_active():
    state = TaskState()
    task = _task("flow_a")
    state.paused.append(task)
    event = state.resume(task.task_id)
    assert isinstance(event, TaskResumed)
    assert state.active.flow_id == "flow_a"


def test_resume_unknown_raises():
    state = TaskState()
    with pytest.raises(ValueError):
        state.resume("nope")
