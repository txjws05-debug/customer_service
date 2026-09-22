from dataclasses import dataclass
from typing import Any

# 数据模型，封装意图识别组件返回数据
@dataclass
class Command:
    command: str
    # 把dict转换不同任务对应的对象
    # 前向引用
    # `{"command": "start_flow", "flow": "<flow_id>"}`
    @classmethod
    def from_dict(cls,command_data: dict) -> "Command":
        # clz  StartFlowCommand
        clz = COMMAND_NAME_TO_CLASS[command_data["command"]]
        return clz(**command_data)


# start_flow
@dataclass
class StartFlowCommand(Command):
    flow: str

# set_slots
@dataclass
class SetSlotsCommand(Command):
    slots: dict[str, Any]

# cancel_task
@dataclass
class CancelTaskCommand(Command):
    task_id: str

# resume_task
@dataclass
class ResumeTaskCommand(Command):
    task_id: str


COMMAND_NAME_TO_CLASS: dict[str, type[Command]] = {
    "start_flow": StartFlowCommand,
    "set_slots": SetSlotsCommand,
    "cancel_task": CancelTaskCommand,
    "resume_task": ResumeTaskCommand,
}