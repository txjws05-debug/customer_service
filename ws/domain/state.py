import time
import uuid
from dataclasses import dataclass,field


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
    closed_at: float | None = None
    turns: list[Turn]=field(default_factory=list)
    # 早期对话的压缩摘要与已摘要轮数：上下文过长时用摘要替代旧原文
    history_summary: str = ""
    summarized_turn_count: int = 0
# 对象类型消息。
#
# 这里是「对话层与业务实体」的唯一接触面：对话层只说「我指的是某个 kind 的
# 某个 id」，至于这个 id 能不能当商品号/订单号用，由这里回答，别处不许自己猜。
#
# 曾经的写法是调用方各写一遍 `if obj.type == 'order' ... else 商品号`，
# 结果「既不是订单也不是商品」的对象（优惠券、未知类型）会被当成商品号去查商品，
# 表现就是线上那句「商品 SO2026… 不存在」。这类判断只能有一处。
KIND_PRODUCT = "product"
KIND_ORDER = "order"
KIND_UNKNOWN = "unknown"

# kind -> 流程槽位名。新增业务对象时只改这张表。
SLOT_BY_KIND: dict[str, str] = {
    KIND_ORDER: "order_number",
    KIND_PRODUCT: "product_id",
}


@dataclass
class FocusedObject:
    type: str
    id: str
    title :str | None = None
    attributes:dict=field(default_factory=dict)

    def __post_init__(self) -> None:
        # 历史数据里 type 可能带空格/大小写不一致，读进来就归一
        self.type = (self.type or "").strip().lower()

    @property
    def kind(self) -> str:
        """受限的类型：只有登记在 SLOT_BY_KIND 里的才算已知对象。"""
        return self.type if self.type in SLOT_BY_KIND else KIND_UNKNOWN

    def is_kind(self, kind: str) -> bool:
        return self.kind == kind

    def product_id(self) -> str | None:
        return self.id if self.kind == KIND_PRODUCT else None

    def order_id(self) -> str | None:
        return self.id if self.kind == KIND_ORDER else None

    def slot_payload(self) -> dict:
        """能直接填进流程槽位的数据；类型不认识时返回空字典，绝不瞎填。"""
        slot = SLOT_BY_KIND.get(self.kind)
        return {slot: self.id} if slot and self.id else {}

    def value_for_slot(self, slot_name: str) -> str | None:
        return self.id if SLOT_BY_KIND.get(self.kind) == slot_name else None

    def label(self) -> str:
        """给提示词用的一句话描述。"""
        return f"{self.kind} {self.id} {self.title or ''}".strip()

@dataclass
class SharedState:

    focuse_object: FocusedObject | None = None
    sessions: list[Session]= field(default_factory=list)

    #创建新session
    def create_session(self):
        now=time.time()
        session=Session(
            session_id=str(uuid.uuid4()),
            started_at=now,
            last_activity_at=now,
        )
        #创建session对象放到state里面
        self.sessions.append(session)
    def close_current_session(self):
        self.sessions[-1].closed_at=time.time()

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
    def start (self,task:TaskInstance)->TaskEvent:
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
    def cancel(self,task_id:str) -> TaskEvent:
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
            self.paused.append(self.active)
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