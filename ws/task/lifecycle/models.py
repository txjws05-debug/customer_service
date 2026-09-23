from dataclasses import dataclass
from typing import TypeAlias

from langchain_protocol import TasksEvent


@dataclass
class TaskRef:
    task_id :str
    flow_id :str

@dataclass
class TaskSwiched:
    previous:TaskRef
    current:TaskRef

@dataclass
class TaskResumed:
    task: TaskRef

@dataclass
class TaskCanceled:
    task: TaskRef

TasksEvent: TypeAlias=(
    TaskStarted
    | TaskSwiched
    | TaskResumed
    | TaskCanceled
)