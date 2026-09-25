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