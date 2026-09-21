from ws.domain.messages import ProcessResult,UserMessage
from ws.engine.dialogue_engine import DialogueEngine
from ws.repository.dialogue_state_repository import (
    DialogyeStateRepository,
)
class DialogueService:
    def __init__(self,dialogue_state_repository:DialogyeStateRepository,dialogue_engine:DialogueEngine,)->None:
        self.dialogue_state_repository=dialogue_state_repository
        self.dialogue_engine=dialogue_engine
    async def process_message(self,user_message:UserMessage,)->ProcessResult:
        state=await self.dialogue_state_repository.load_state(user_message.sender_id)
        process_result=await self.dialogue_engine.process_message(state,user_message,)
        await self.dialogue_state_repository.save_state(state)