import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ws.api.auth_router import auth_router
from ws.api.chat_router import chat_router
from ws.config.config import settings
from ws.engine.builder import build_dailogue_engine
from ws.knowledge.reindex import ensure_index
from ws.utils import database
from ws.utils.errors import ChatServiceError
from ws.utils.http import close_http_client, init_http_client
from ws.utils.logging_config import setup_logging

logger = logging.getLogger("ws.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    setup_logging()
    database.init_db_engine()
    await database.create_tables()
    # 知识库建表 + 建向量索引（语料/模型变了会自动重建）。
    # 失败只告警：检索不可用不该拖垮整个客服服务。
    if settings.knowledge_auto_index:
        try:
            result = await ensure_index()
            logger.info("知识库就绪：%d 条，embedding=%s（%s）",
                        result.chunks, result.embedding_backend, result.reason)
        except Exception:  # noqa: BLE001
            logger.exception("知识库索引建立失败，FAQ/RAG 检索将不可用")
    init_http_client()
    # 对话引擎只构建一次，所有请求共享
    app.state.dialogue_engine = build_dailogue_engine()
    logger.info("Application startup complete")
    yield
    # ---- shutdown ----
    await close_http_client()
    await database.close_db_engine()
    logger.info("Application shutdown complete")


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(chat_router)


# 业务可预期错误统一返回 400，detail 可直接展示给用户
@app.exception_handler(ChatServiceError)
async def chat_service_error_handler(request: Request, exc: ChatServiceError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# 兜底：未预期异常返回 500 + 友好提示，并记录完整 traceback
@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # 保留 HTTPException（401/404 等）原本的状态码与 detail
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
    logger.exception("Unhandled error on %s %s",
                     request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器开小差了，请稍后再试。"})
