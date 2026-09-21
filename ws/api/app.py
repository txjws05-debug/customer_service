from fastapi import FastAPI
from ws.api.chat_router import chat_router
app=FastAPI()
app.include_router(chat_router)