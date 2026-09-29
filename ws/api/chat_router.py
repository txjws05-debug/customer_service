import json
import uuid
from dataclasses import asdict

from fastapi import APIRouter
from  fastapi.params import Depends
from fastapi.responses import StreamingResponse

from ws.api.schemas import HistoryResponse
from ws.api.schemas import ChatRequest, ChatResponse, ChatMessage, ChatObject, HistoryMessage
from ws.api.deps import get_dialogue_service, get_current_user
from ws.domain.message import UserMessage,ProcessResult,MessageType,MessageObject
from ws.domain.state import DialogueState, Session, Turn
from ws.service.dialogue_service import DialogueService
from ws.utils.errors import ChatServiceError

chat_router=APIRouter()


@chat_router.post("/api/chat")
async def chat(chat_request:ChatRequest ,
         current_user:str=Depends(get_current_user),
         dialogue_service:DialogueService=Depends(get_dialogue_service)
         )->ChatResponse:

    user_message:UserMessage=_build_user_message(chat_request,current_user)
    process_result:ProcessResult=await dialogue_service.process_message(user_message)
    return _build_chat_response(process_result)

# 流式对话（SSE）：逐段返回 {"text": "增量"}，结束发 [DONE]
@chat_router.post("/api/chat/stream")
async def chat_stream(chat_request:ChatRequest,
                      current_user:str=Depends(get_current_user),
                      dialogue_service:DialogueService=Depends(get_dialogue_service)):
    user_message:UserMessage=_build_user_message(chat_request,current_user)

    async def event_generator():
        try:
            async for delta in dialogue_service.process_message_stream(user_message):
                if delta:
                    yield f"data: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
        except ChatServiceError as exc:
            # 流式过程中的业务错误，作为 error 事件下发，再正常结束
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(),
                             media_type="text/event-stream")

#ChatRequest转换 UserMessage
def _build_user_message(chat_request:ChatRequest,sender_id:str)->UserMessage:
    return UserMessage(
         sender_id=sender_id,
         message_id=chat_request.message_id
         if chat_request.message_id else str (uuid.uuid4()),
         type=MessageType.TEXT if chat_request.text else MessageType.OBJECT,
         text=chat_request.text,
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
# 返回当前用户历史记录
@chat_router.post("/api/chat/history")
async def chat_history(current_user:str=Depends(get_current_user),
                       dialogue_service:DialogueService=Depends(get_dialogue_service)
                       )->HistoryResponse:
    #调用service方法，返回 查询出来的DialogueState对象
    history_session:DialogueState=(
        await dialogue_service.get_history_session_send_id(current_user)
    )
    #history_session:DialogueState取出来，封装到iHistoryResponse
    sessions:list[Session] = history_session.share.sessions

    #类型HistoryMessage变量，封装多个HistoryMessage数据
    messages:list[HistoryMessage] =[]
    #sessions : list[sessions]遍历得到每个Session
    for session in sessions:
        #每个session获取多轮对话
        turns:list[Turn]=session.turns
        #turns:list[Turn] 遍历
        for turn in turns:
            #封装用户提问问题
            messages.append(
                HistoryMessage(
                    role="user",
                    text= turn.user_message.text,
                    object=ChatObject(
                        **asdict(turn.user_message.object))
                    if turn.user_message.object else None,
                )
            )

            #封装客服回复数据
            messages.extend([
                HistoryMessage(
                    role="bot",
                    text= bo_msg.text,
                    object=ChatObject(
                        **asdict(bo_msg.object))
                        if bo_msg.object else None,
                    )
                for bo_msg in turn.bot_message
            ])

    return HistoryResponse(sender_id=current_user,messages=messages)