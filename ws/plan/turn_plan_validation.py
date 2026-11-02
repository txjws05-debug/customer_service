
from ws.task.command.models import StartFlowCommand, ResumeTaskCommand, CancelTaskCommand
from ws.domain.state import DialogueState
from ws.plan.models import TurnPlan, TurnPlanValidationResult, ClarifyReason,TaskTurnPlan
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
            # 一句话只能办一件事，但不该因此把用户挡在门外。
            # 「还没发货，能改收货地址吗」里「还没发货」是前提，不是第二个请求；
            # 判成多轨道再反问「您想先处理哪个」，用户只会觉得系统没听懂。
            # 这里按「办理 > 咨询 > 闲聊」取优先级最高的一个，其余丢弃。
            # 代价：一句话里真提了两件事时只回应其中一件，用户会再说一遍——
            # 这比先反问一句更接近人与人对话的实际节奏。
            preferred = None
            if turn_plan.task is not None and turn_plan.task.commands:
                preferred = "task"
            elif turn_plan.knowledge is not None:
                preferred = "knowledge"
            elif turn_plan.chitchat is not None:
                preferred = "chitchat"
            active_tracks = [preferred or active_tracks[0]]
        #只有一个轨道
        active_tracks=active_tracks[0]
        if active_tracks=="task":
           return self._validate_task_plan(
               task= turn_plan.task,state=state,flow_catalog=flow_catalog
           )
        if active_tracks=="knowledge":
            return self._validate_knowledge_plan()
        return TurnPlanValidationResult(valid=True)
    #对task意图识别
    def _validate_task_plan(self,
                            task:TaskTurnPlan,
                            state: DialogueState,
                            flow_catalog:FlowCatalog
                                ):
        if not task.commands:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MISSING_TASK_COMMANDS
            )
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
                # 取消一个「对不上」的任务不判非法指令。
                # 「算了不买了」时任务往往已经结束（订单都建好了），模型给回的
                # task_id 自然匹配不上任何 active/paused。这是正常对话行为，
                # 交给命令处理器回一句「好的，这次就不办了」，
                # 比反问「抱歉，这个操作我暂时无法完成」有用得多。
                if command.task_id not in all_task_ids:
                    continue

        return TurnPlanValidationResult(valid=True)

    def _validate_knowledge_plan(self):
        return TurnPlanValidationResult(valid=True)