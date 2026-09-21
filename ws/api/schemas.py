from pydantic import BaseModel


class ChatObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict = {}


class ChatRequest(BaseModel):
    sender_id: str
    text: str | None = None
    object: ChatObject | None = None
    message_id: str | None = None


class ChatMessage(BaseModel):
    text: str | None = None
    object: ChatObject | None = None


class ChatResponse(BaseModel):
    sender_id: str
    message_id: str
    messages: list[ChatMessage]