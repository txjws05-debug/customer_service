from dataclasses import dataclass,field
from ws.domain.message import UserMessage,BotMessage



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
    sessions: list[Session] | None

@dataclass
class TaskInstance:
    flow_id: str
    step_id: str
    task_id: str
    slots: dict=field(default_factory=dict)



@dataclass
class TaskState:
    active:TaskInstance | None = None
    paused:list[TaskInstance] = field(default_factory=list)

@dataclass
class DialogueState:

    sender_id: str
    share: SharedState=field(default_factory=SharedState)
    tasks: TaskState=field(default_factory=TaskState)