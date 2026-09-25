from plan.models import TaskTurnPlan
from task.command.models import StartFlowCommand, ResumeTaskCommand, CancelTaskCommand
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
    def _validate_task_plan(self,
                            task:TaskTurnPlan,
                            state: DialogueState,
                            flow_catalog:FlowCatalog
                                ):
        #根据不同类型的command做不同检验
        for command in task.commands:
            #1 start_flow 校验flow_id是否存在于当前流程里面yaml里面
            if isinstance(command,StartFlowCommand):
                #获取start_flow流程id
                flow_id =command.flow
                #校验flow_id是否存在于当前流程里面yaml里面
                if flow_id not in flow_catalog.flows:
                    return  TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND
                    )
            #2 resume_task校验task_id 是否存在于中断列表
            if isinstance(command,ResumeTaskCommand):
                #判断回复任务id在中断列表是否存在
                #获取中断列表索引任务id
                #[1,2,3]
                paused_task_ids=[paused_task.task_id
                                 for paused_task in state.tasks.paused]
                #当前command任务id和所有中断列表任务id比较
                if command.task_id not in paused_task_ids:
                    return TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND
                    )
            #3 cancal_task 校验task_id 是否存在于 中断列表 或者当前任务里面
            if  isinstance(command,CancelTaskCommand):
                #获取中断列表任务所有id
                all_task_ids=[paused_task.task_id
                              for paused_task in state.tasks.paused  ]
                #获取当前活跃任务id
                if state.tasks.active:
                    all_task_ids.append(state.tasks.active.task_id)
                #判断
                if command.task_id not in all_task_ids:
                    return  TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND
                    )

        return TurnPlanValidationResult(valid=True)

    def _validate_knowledge_plan(self):
        pass