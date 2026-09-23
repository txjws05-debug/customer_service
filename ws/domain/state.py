import uuid
from dataclasses import dataclass,field

from langchain_protocol import TasksEvent
from typing_inspection.typing_objects import target

from ws.domain.message import UserMessage,BotMessage
from ws.task.lifecycle.models import TaskEvent, TaskSwitched, TaskStarted, TaskRef, TaskCanceled, TaskResumed


@dataclass
class Turn:
    turn_id: str

    user_message: UserMessage

    bot_message: list[BotMessage]=field(default_factory=list)
#会话对象
@dataclass
class Session:
    session_id: str
    started_at: float
    last_activity_at: float
    closed_at: float
    turns: list[Turn]=field(default_factory=list)
#对象类型消息
@dataclass
class FocusedObject:
    type: str
    id: str
    title :str | None = None
    attributes:dict=field(default_factory=dict)

@dataclass
class SharedState:

    focuse_object: FocusedObject | None
    sessions: list[Session]= field(default_factory=list)

@dataclass
class TaskInstance:
    flow_id: str
    step_id: str | None = None
    task_id: str=field(default_factory=lambda :str(uuid.uuid4()))
    slots: dict=field(default_factory=dict)
    def to_ref(self)->TaskRef:
        return TaskRef(task_id=self.task_id,
                       flow_id= self.flow_id)



@dataclass
class TaskState:
    active:TaskInstance | None = None
    paused:list[TaskInstance] = field(default_factory=list)
    #开始流程
    def start (self,task:TaskInstance)->TasksEvent:
        if self.active:
            previous= self.active.to_ref()
            self.paused.append(self.active)

            self.active=task
            current=self.active.to_ref()
            return TaskSwitched(previous=previous,current=current)
        else:
            self.active=task
            return TaskStarted(task=self.active.to_ref())
    #取消流程
    def cancle(self,task_id:str) -> TaskEvent:
        if self.active.task_id ==task_id:
            target_task = self.active.to_ref()
            self.active=None
            return TaskCanceled(task=target_task)
        else:
            for pause_task in self.paused:
                if pause_task.task_id==task_id:
                    target_task=pause_task.to_ref()
                    self.paused.remove(pause_task)
                    return TaskCanceled(task=target_task)
            raise ValueError("任务不存在")
    def resume(self,task_id:str)-> TaskEvent:
        target_task_ref=None
        target_task=None
        for index,task in enumerate(self.paused):
            if task.task_id==task_id:
                target_task_ref=task.to_ref()
                target_task=self.paused.pop(index)
                break

        if target_task is None:
            raise ValueError("恢复任务不存在")
        if self.active:
            previous_task_ref = self.active.to_ref()

            self.active=target_task
            return TaskSwitched(previous=previous_task_ref,
                                current=target_task_ref)

        else:
            self.active=target_task
            return TaskResumed(task=target_task_ref)

@dataclass
class DialogueState:

    sender_id: str
    share: SharedState=field(default_factory=SharedState)
    tasks: TaskState=field(default_factory=TaskState)