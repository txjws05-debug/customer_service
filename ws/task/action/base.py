from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ws.domain.state import DialogueState

#封装action的属性值
@dataclass()
class ActionCall:
    #必须
    action_name: str
    #可选
    action_kwargs: dict[str,Any]=field(
        default_factory=dict
    )
#封装中台接口返回数据
@dataclass()
class ActionResult:
    slot_updates: dict[str,Any]=field(default_factory=dict)

#action基类
class Action(ABC):
    name : str=""
    @abstractmethod
    async def run(
            self,
            state:DialogueState,
            action_kwargs:dict[str,Any],
                  )->ActionResult:
        pass