from fastapi import FastAPI
from ws.api.auth_router import auth_router
from ws.api.chat_router import chat_router
app=FastAPI()
app.include_router(auth_router)
app.include_router(chat_router)
