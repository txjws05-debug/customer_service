import time
import uuid

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
    def _execute_text_message(self,user_message:UserMessage,state:DialogueState)->list[BotMessage]:
        #1根据user——message文本提问信息，调用llm，进行意图识别
        #识别执行哪个轨道：任务流程、知识检索、闲聊
        #如果任务流程，识别流程id

        #2 对llm意图识别结果校验
        ##如有两个轨道，任务流程识别流程id不存在


        #校验失败，调用反问澄清组件

        #校验成功，根据识别不同轨道，调用不同handler处理
        #比如识别任务流程调用TaskHandelr方法执行
        

        pass

     #处理对象类型消息
    def _execute_object_message(self,user_message,state):
        pass





