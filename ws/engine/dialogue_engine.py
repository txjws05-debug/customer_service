import time
import uuid
from dataclasses import asdict


from domain.state import FocusedObject
from plan.models import TurnPlanValidationResult
from task.command.models import SetSlotsCommand
from task.flow.models import Flow
from task.flow.steps import FlowStep, CollectSlotStep
from ws.domain.message import UserMessage, ProcessResult, MessageType, BotMessage
from ws.domain.state import DialogueState, Turn
from ws.plan import turn_plan
from ws.plan.turn_plan import TurnPlan
from ws.plan.turn_plan_validation import TurnPlanValidation
from ws.task.handler import TaskHandler

class DialogueEngine:
    #处理消息
    def __init__(self,trun_plan: TurnPlan,
                 turn_plan_validation:TurnPlanValidation,
                 task_handler: TaskHandler
                 ):
        self._turn_plan=trun_plan,
        self._turn_plan_validation=turn_plan_validation
        self.task_handler=task_handler

    async def process_message(self,state:DialogueState,user_message:UserMessage)->ProcessResult:
        #准备当前会话
        self._prepare_session(state)
        #准备本来Turn
        turn=Turn(turn_id=str(uuid.uuid4()),user_message=user_message)
        #3判断消息类型
        #文本消息类型
        if user_message.type==MessageType.TEXT:
            messages:list[BotMessage]=self._execute_text_message(user_message,state)
            #对象消息类型
        else :
            messages: list[BotMessage]=self._execute_object_message(user_message,state)

        #提交本轮对话记录
        ##封装list[BotMessage]到turn对象
        turn.bot_message.extend(messages)
        #放到当前session里面
        state.share.sessions[-1].turns.append(turn)

        #返回本轮回复
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages
        )
    def _prepare_session(self,state:DialogueState):
        #判断当前session存在
        #不存在session
        if not state.share.sessions:
            state.share.create_session()
        #存在session
        #判断session是否过期
        else:
            current_session= state.share.sessions[-1]
            now = time.time()
            #判断是否过期
            if now - current_session.last_activity_at >60*60:
                #手动session过期
                state.share.close_current_session()
                #创建新session
                state.share.create_session()

            # session没有过期
            else:
                #更新
                current_session.last_activity_at=now
    #处理文本类型消息
    async def _execute_text_message(self,user_message:UserMessage,state:DialogueState)->list[BotMessage]:
        #1根据user——message文本提问信息，调用llm，进行意图识别
        #识别执行哪个轨道：任务流程、知识检索、闲聊
        #如果任务流程，识别流程id
        turnPlan:TurnPlan = await self._turn_plan.plan(user_message=user_message,
                                                       state=state,
                                                       flow_catalog=self.task_handler._flow_catalog)
        #2 对llm意图识别结果校验
        ##如有两个轨道，任务流程识别流程id不存在
        validation:TurnPlanValidationResult=self._turn_plan_validation.validate(turn_plan=turnPlan,
                                                                                state=state,
                                                                                flow_catalog=self._task_handler._flow_catalog)

        #校验失败，调用反问澄清组件
        if not validation.valid:
            #todo 反问澄清插件
            pass
        #校验成功，根据识别不同轨道，调用不同handler处理
        #比如识别任务流程调用TaskHandelr方法执行
        if turnPlan.task:
            return  await self.task_handler.handle(
                commands=turnPlan.task.command,
                state=state,
                user_message=user_message
            )
        if turnPlan.knowledge:
            pass
        if  turnPlan.chitchat:
            pass


     #处理对象类型消息
    async def _execute_object_message(self,user_message,state):
        #1把对象消息放到state里面focused_object
        state.share.focuse_object=FocusedObject(
            **asdict(user_message.object)
        )
        #判断是否填充槽位数据
        if self._can_fill_slots(state):
            if user_message.object.type=='order':
                slots={'order_number':user_message.object.id}
            else :
                slots={'product_id':user_message.object.id}
        # 最终调TaskHandler里面方法，传入command对象，对象类型消息处理
        #没有调用意图识别组件，没有command
        #手动构建command对象设置对应类型
        #{"command":"set_slots",{"<slot_name>":"<value>"}}
            command=SetSlotsCommand(
            command='set_slots',
            slots=slots
        )
            #调用TaskHandler方法执行
            return await self.task_handler.handle(
            command=[command],
            state=state,
            user_message=user_message,
        )
        else:
            # 反问澄清
            pass
    def _can_fill_slots(self,state:DialogueState) -> bool:
        #1判断当前是否有活跃任务
        active_task=state.tasks.active
        if not active_task:
            return False
        #有活跃任务
        #根据当前任务流程id，获取流程对象
        flow_id= active_task.flow_id
        flow:Flow =self.task_handler._flow_catalog.get_flow_by_id(flow_id)

        #从流程对象获取所有步骤列表，当前任务步骤id到列表找到步骤对应数据
        step:FlowStep=flow.get_step_by_id(active_task.step_id)
        #判断当前步骤是否collect类型
        if not isinstance(step,CollectSlotStep):
            return False

        if(step.solt_name=='order_number') and(state.share.focuse_object.type=='order'):
            return True

        if (step.solt_name=='product_id')and (state.share.focuse_object.type=='product'):
            return True
        return False




