

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.task.command.models import Command
from ws.task.command.processor import CommandProcessor
from ws.task.flow.executor import FlowExecutor
from ws.task.flow.models import FlowCatalog
from ws.task.lifecycle.models import TaskEvent
from ws.task.lifecycle.responder import TaskLifecycleResponder

class TaskHandler:
    def __init__(self,
                 command_processor:CommandProcessor,
                 task_lifecycle:TaskLifecycleResponder,
                 flow_executor:FlowExecutor,
                 flow_catalog:FlowCatalog):
        self._command_processor=command_processor
        self._task_lifecycle=task_lifecycle
        self._flow_executor=flow_executor
        self._flow_catalog=flow_catalog
    async def handle(self,commands:list[Command],
                     state:DialogueState,
                     user_message:UserMessage)-> list[BotMessage]:
        task_events:list[TaskEvent]=await self._command_processor.run(
            commands=commands,state=state,flows=self._flow_catalog)

        messages:list[BotMessage] =await self._task_lifecycle.respond(task_events)
        result:list[BotMessage]= await self._flow_executor.run_task(
            state=state,
            user_message=user_message,
            flows=self._flow_catalog
        )
        messages.extend(result)
        return messages

    # 流式版本：命令处理后，逐段 yield（生命周期提示 + 流程推进回复）
    async def stream(self,commands:list[Command],
                     state:DialogueState,
                     user_message:UserMessage):
        task_events:list[TaskEvent]=await self._command_processor.run(
            commands=commands,state=state,flows=self._flow_catalog)
        lifecycle_msgs:list[BotMessage]=await self._task_lifecycle.respond(task_events)
        for m in lifecycle_msgs:
            yield m.text
        async for delta in self._flow_executor.run_task_stream(
                state=state,user_message=user_message,flows=self._flow_catalog):
            yield delta