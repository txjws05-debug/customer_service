from ws.domain.state import DialogueState, TaskInstance
from ws.task.command.models import (
    Command,
    StartFlowCommand,
    SetSlotsCommand,
    CancelTaskCommand,
    ResumeTaskCommand,
)
from ws.task.flow.models import FlowCatalog
from ws.task.lifecycle.models import TaskEvent
from ws.utils.errors import ChatServiceError


class CommandProcessor:
    async def run(
            self, commands: list[Command],
            state: DialogueState,
            flows: FlowCatalog,
    ) -> list[TaskEvent]:
        events: list[TaskEvent] = []

        for command in commands:
            try:
                event = self._apply(
                    command=command, state=state, flow_catalog=flows)
            except ValueError as exc:
                # TaskState 在任务不存在时抛 ValueError，统一转为业务错误
                raise ChatServiceError(str(exc))
            if event:
                events.append(event)
        return events

    def _apply(self, command: Command,
               state: DialogueState,
               flow_catalog: FlowCatalog
               ) -> TaskEvent | None:

        if isinstance(command, StartFlowCommand):
            flow_id = command.flow
            flow = flow_catalog.get_flow_by_id(flow_id)
            start_step = flow.get_start_step()
            task = TaskInstance(
                flow_id=flow_id,
                step_id=start_step.id
            )
            return state.tasks.start(task)

        if isinstance(command, SetSlotsCommand):
            # 没有活跃任务时无法填充槽位，避免 AttributeError
            if state.tasks.active is None:
                raise ChatServiceError(
                    "当前没有进行中的任务，请先告诉我你要办理什么业务。")
            state.tasks.active.slots.update(command.slots)
            return None

        if isinstance(command, CancelTaskCommand):
            return state.tasks.cancel(command.task_id)

        if isinstance(command, ResumeTaskCommand):
            return state.tasks.resume(command.task_id)

        raise ChatServiceError(f"不支持的指令类型：{command.command}")
