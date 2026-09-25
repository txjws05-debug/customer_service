from ws.domain.state import DialogueState
from ws.plan.models import TurnPlan, TurnPlanValidationResult, ClarifyReason
from ws.task.flow.models import FlowCatalog


class TurnPlanValidation:
    def validate(self,
                 turn_plan:TurnPlan,
                 state:DialogueState,
                 flow_catalog: FlowCatalog
                 ) -> TurnPlanValidationResult:
        #判断是否多个轨道
        active_tracks: list[str]=[]
        if turn_plan.task is not  None:
            active_tracks.append("task")

        if turn_plan.knowledge is not None:
            active_tracks.append("knowledge")
        if turn_plan.chitchat is not None:
            active_tracks.append("chitchat")
            #没有识别到
        if not active_tracks:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MISSING_TRACK
            )
        if len(active_tracks)>1:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MULTIPLE_TRACKS
            )
        #只有一个轨道
        active_tracks=active_tracks[0]
        if active_tracks=="task":
            self._validate_task_plan()
        if active_tracks=="knowledge":
            self._validate_knowledge_plan()
        return TurnPlanValidationResult(valid=True)
    #对task意图识别
    def _validate_task_plan(self):
        #根据不同类型的command做不同检验
        pass

    def _validate_knowledge_plan(self):
        pass