"""请求级 trace_id（中台侧）。

与客服 Agent 侧的实现刻意保持一致：读到 `X-Request-Id` 就复用，没有才生成。
这样一次用户提问在 Agent 与中台两个容器的日志里是**同一个 id**，
`docker logs cs-backend | grep <id>` 和 `docker logs cs-ecommerce | grep <id>`
能拼出完整链路。
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

TRACE_FIELD = "trace_id"
_var: ContextVar[str] = ContextVar("trace_id", default="-")

logger = logging.getLogger("ecommerce.trace")

_FORMAT = "%(asctime)s %(levelname)-7s [" + "%(" + TRACE_FIELD + ")s] %(name)s: %(message)s"


def current_trace_id() -> str:
    return _var.get()


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, TRACE_FIELD, None):
            setattr(record, TRACE_FIELD, _var.get())
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """给中台配一个带 trace_id 的根日志格式。

    中台原本没有日志配置（全靠 uvicorn 默认），不配的话格式里没有 trace_id，
    这个字段就白加了。
    """
    logging.basicConfig(level=level, format=_FORMAT,
                        datefmt="%Y-%m-%d %H:%M:%S", force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(TraceIdFilter())


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = (request.headers.get("x-request-id") or "").strip()
        trace_id = incoming or uuid.uuid4().hex[:12]
        token = _var.set(trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("%s %s 异常 耗时%.0fms", request.method,
                             request.url.path,
                             (time.perf_counter() - started) * 1000)
            _var.reset(token)
            raise
        # 健康检查每 15 秒一次，进日志只会把真正的问题埋掉
        if request.url.path != "/health":
            logger.info("%s %s -> %s 耗时%.0fms", request.method,
                        request.url.path,
                        response.status_code,
                        (time.perf_counter() - started) * 1000)
        # 健康检查不回头：容器探针不看，外部也不该从这拿到任何信息
        if request.url.path != "/health":
            response.headers["X-Request-Id"] = trace_id
        _var.reset(token)
        return response
