from ws.domain.state import DialogueState, TaskInstance
from ws.task.command.models import Command, StartFlowCommand, SetSlotsCommand, CancelTaskCommand, ResumeTaskCommand
from ws.task.flow.models import FlowCatalog, Flow
from ws.task.flow.steps import StartFlowStep

class CommandProcessor:
    def run(
            self,commands:list[Command],
            state:DialogueState,
            flows:FlowCatalog,
            ) ->list[TaskEvent]:
        events: list[TaskEvent]=[]

        for command in commands:
            event=self._apply(command=command,
                               state=state,
                               flows=flows)
            if event:
                events.append(event)
        return events

    def _apply(self,command:Command,
               state:DialogueState,
               flow_catalog:FlowCatalog
               )->TaskEvent:

        if isinstance(command,StartFlowCommand):
            flow_id=command.flow

            flow:Flow=flow_catalog.get_flow_by_id(flow_id)

            start_step:StartFlowStep=flow.get_start_step()
            task=TaskInstance(
                flow_id=flow_id,
                step_id=start_step.id
            )

            if isinstance(command,SetSlotsCommand):
                state.tasks.active.slots.update(command.slots)
                return None

            if isinstance(command,CancelTaskCommand):
                event: TaskEvent=state.tasks.cancel(command.task_id)
                return event
            if isinstance(command,ResumeTaskCommand):
                event : TaskEvent=state.tasks.resusme(command.task_id)
                return event
