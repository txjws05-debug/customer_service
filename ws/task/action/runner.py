from ws.domain.state import DialogueState
from ws.task.action.base import ActionCall, ActionResult, Action
from ws.task.action.registry import  ActionRegistory


class ActionRunner:
    def __init__(self,registry:ActionRegistory):
        self._registry=registry

    async  def run(self,action_call:ActionCall,
                   state:DialogueState)-> ActionResult:
        action_name=action_call.action_name
        action:Action =self._registry.get_action(action_name)
        return  await action.run(state=state,
                                 action_kwargs=action_call.action_kwargs)


