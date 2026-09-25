from ws.task.action.base import Action

class ActionRegistory:
    def __init__(self):
        self._action:dict[str,Action]={}


    def register_action(self,action:Action):
        self._action[action.name]=action

    def get_action(self,name:str) -> Action:
        return self._action[name]
    