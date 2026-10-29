import logging
from contextlib import asynccontextmanager

import hmac

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ws import metrics
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ws.api.auth_router import auth_router
from ws.api.chat_router import chat_router
from ws.api.handoff_router import router as handoff_router
from ws.config.config import settings
from ws.engine.builder import build_dailogue_engine
from ws.knowledge.reindex import ensure_index
from ws.utils import database
from ws.utils.errors import ChatServiceError
from ws.utils.http import close_http_client, init_http_client
from ws.trace import TraceMiddleware
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


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if settings.expose_docs else None,
    redoc_url="/redoc" if settings.expose_docs else None,
    openapi_url="/openapi.json" if settings.expose_docs else None,
)


# 最后添加 = 最外层：先绑 trace_id，再进业务与鉴权，
# 这样连 401/500 的日志也带得上 id
app.add_middleware(TraceMiddleware)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    """Prometheus 抓取端点。

    只在内网暴露（Caddy 不转发 /metrics），且可选用 Bearer 令牌再上一道锁 ——
    指标里有路径、错误率、耗时分布，等于系统的运行画像。
    """
    expected = settings.metrics_token
    if expected:
        got = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(got.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="metrics 需要访问令牌")
    return PlainTextResponse(metrics.render(),
                             media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/health", summary="健康检查（匿名、不碰数据库）")
async def health() -> dict:
    """容器健康检查专用。

    必须匿名且不查库：鉴权失败或数据库慢都不该让容器被判死、反复重启。
    """
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(handoff_router)


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
