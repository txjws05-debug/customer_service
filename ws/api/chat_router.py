import uuid
from dataclasses import asdict

from fastapi import APIRouter
from  fastapi.params import Depends
from ws.api.schemas import ChatRequest, ChatResponse, ChatMessage, ChatObject
from ws.api.depends import get_dialogue_service
from ws.domain.message import UserMessage,ProcessResult,MessageType,MessageObject
from ws.service.dialogue_service import DialogueService

chat_router=APIRouter()


@chat_router.post("/api/chat")
async def chat(chat_request:ChatRequest ,
         dialogue_service:DialogueService=Depends(get_dialogue_service)
         )->ChatResponse:

    user_message:UserMessage=_build_user_message(chat_request)
    process_result:ProcessResult=await dialogue_service.process_message(user_message)
    return _build_chat_response(process_result)

#ChatRequest转换 UserMessage
def _build_user_message(chat_request:ChatRequest)->UserMessage:
    return UserMessage(
         sender_id=chat.sender_id,
         message_id=chat_request.message_id
         if chat_request.message_id else str (uuid.uuid4()),text=chat_request.text,
         object=MessageObject(
             type=chat_request.object.type,
             id=chat_request.object.id,
             title=chat_request.object.title,
             attributes=chat_request.object.attributes
         ) if chat_request.object else None,

     )
# ProcessResult => ChatResponse
def _build_chat_response(process_result:ProcessResult)->ChatResponse:

    return ChatResponse(
        sender_id=process_result.sender_id,
        message_id=process_result.message_id,
        messages=[
            ChatMessage(
                text=message.text,
                object=ChatObject(
                    **asdict(message.object)
                ) if message.object else None,
            ) for message  in process_result.messages
        ]
    )