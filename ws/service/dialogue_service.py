from ws.domain.message import BotMessage, ProcessResult,UserMessage
from ws.domain.state import DialogueState
from ws.engine.dialogue_engine import DialogueEngine
from ws.repository.dialogue_repository import DialogueRepository
from ws.service.handoff_service import HandoffService

class DialogueService:
    def __init__(self,dialogue_repository:DialogueRepository,dialogue_engine:DialogueEngine,
                 handoff_service:HandoffService|None=None)->None:
        self.dialogue_repository=dialogue_repository
        self.dialogue_engine=dialogue_engine
        # 可为空：纯单测里不需要人工接管
        self.handoff_service=handoff_service
    async def process_message(self,user_message:UserMessage)->ProcessResult:
        #根据用户id查找对话
        sender_id = user_message.sender_id
        # 人工接管优先于一切：已转人工或已有工单时不调 LLM
        notice=await self._handoff_notice(user_message)
        if notice:
            return ProcessResult(sender_id=sender_id,message_id=user_message.message_id,
                                 messages=[BotMessage(text=notice)])
        state:DialogueState=await self.dialogue_repository.load(sender_id)

        process_result:ProcessResult= await self.dialogue_engine.process_message(state,user_message)

        await self.dialogue_repository.save(state)
        return process_result

    # 流式处理：逐段 yield，结束后统一落库
    async def process_message_stream(self,user_message:UserMessage):
        notice=await self._handoff_notice(user_message)
        if notice:
            yield notice
            return
        state:DialogueState=await self.dialogue_repository.load(
            user_message.sender_id)
        async for delta in self.dialogue_engine.process_message_stream(
                state,user_message):
            yield delta
        await self.dialogue_repository.save(state)

    async def _handoff_notice(self,user_message:UserMessage)->str|None:
        if self.handoff_service is None:
            return None
        return await self.handoff_service.intercept(
            user_message.sender_id, getattr(user_message, "text", None))

    # 根据用户id查询历史记录
    async  def get_history_session_send_id(self,sender_id)->DialogueState:
        state : DialogueState =await  self.dialogue_repository.load(sender_id)
        return state
