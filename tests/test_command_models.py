import asyncio

import pytest

from ws.domain.state import DialogueState
from ws.task.command.models import (
    CancelTaskCommand,
    Command,
    ResumeTaskCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from ws.task.command.processor import CommandProcessor
from ws.utils.errors import ChatServiceError


def test_start_flow_from_dict():
    cmd = Command.from_dict(
        {"command": "start_flow", "flow": "logistics_tracking"})
    assert isinstance(cmd, StartFlowCommand)
    assert cmd.flow == "logistics_tracking"


def test_set_slots_from_dict():
    cmd = Command.from_dict(
        {"command": "set_slots", "slots": {"order_number": "A1001"}})
    assert isinstance(cmd, SetSlotsCommand)
    assert cmd.slots == {"order_number": "A1001"}


def test_resume_from_dict():
    cmd = Command.from_dict(
        {"command": "resume_task", "task_id": "t1"})
    assert isinstance(cmd, ResumeTaskCommand)
    assert cmd.task_id == "t1"


def test_cancel_from_dict():
    cmd = Command.from_dict(
        {"command": "cancel_task", "task_id": "t1"})
    assert isinstance(cmd, CancelTaskCommand)


def test_unknown_command_raises():
    with pytest.raises(ChatServiceError):
        Command.from_dict({"command": "fly_to_moon"})


def test_set_slots_without_active_raises():
    from pathlib import Path
    from ws.task.flow.loader import FlowLoader
    processor = CommandProcessor()
    state = DialogueState(sender_id="u1")
    flow_path = (Path(__file__).parents[1]
                 / 'ws' / 'config' / 'user_flows.yml')
    flows = FlowLoader().load(flow_path)
    with pytest.raises(ChatServiceError):
        asyncio.run(processor.run(
            [SetSlotsCommand(command="set_slots", slots={"a": 1})],
            state, flows))
