from ws.domain.message import ProcessResult,UserMessage
from ws.domain.state import DialogueState
from ws.engine.dialogue_engine import DialogueEngine
from ws.repository.dialogue_repository import DialogueRepository

class DialogueService:
    def __init__(self,dialogue_repository:DialogueRepository,dialogue_engine:DialogueEngine,)->None:
        self.dialogue_repository=dialogue_repository
        self.dialogue_engine=dialogue_engine
    async def process_message(self,user_message:UserMessage)->ProcessResult:
        #根据用户id查找对话
        sender_id = user_message.sender_id
        state:DialogueState=await self.dialogue_repository.load(sender_id)

        process_result:ProcessResult= await self.dialogue_engine.process_message(state,user_message)

        await self.dialogue_repository.save(state)
        return process_result

    # 流式处理：逐段 yield，结束后统一落库
    async def process_message_stream(self,user_message:UserMessage):
        state:DialogueState=await self.dialogue_repository.load(
            user_message.sender_id)
        async for delta in self.dialogue_engine.process_message_stream(
                state,user_message):
            yield delta
        await self.dialogue_repository.save(state)

    # 根据用户id查询历史记录
    async  def get_history_session_send_id(self,sender_id)->DialogueState:
        state : DialogueState =await  self.dialogue_repository.load(sender_id)
        return state
