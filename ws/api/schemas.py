from pydantic import BaseModel


class AuthRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class ChatObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict = {}


class ChatRequest(BaseModel):
    # 身份从 JWT 解析，sender_id 不再由前端提供（保留字段仅为兼容）
    sender_id: str | None = None
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
class HistoryMessage(BaseModel):
    role :str #user/bot
    text:str | None = None
    object:ChatObject | None = None
class HistoryResponse(BaseModel):
    sender_id: str
    messages: list[HistoryMessage]