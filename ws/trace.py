"""请求级 trace_id 的中间件。

一个用户请求会跨越三段：浏览器 → 客服 Agent → 电商中台 → PostgreSQL。
出问题时最想要的是「把这个 id 相关的日志全捞出来」，而不是在时间戳相近的
几百行里猜哪几行属于同一次请求。

上下文变量与过滤器放在 logging_config（避免日志模块反向 import 中间件），
这里只负责「入口生成/继承 → 出口回写响应头 → 记一行访问日志」。
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from ws import metrics
from ws.utils.logging_config import (
    bind_trace_id,
    current_trace_id,
    reset_trace_id,
)

logger = logging.getLogger("ws.trace")


def new_trace_id() -> str:
    """12 位十六进制：够短、能人读，单机请求量下碰撞概率可忽略。"""
    return uuid.uuid4().hex[:12]


class TraceMiddleware(BaseHTTPMiddleware):
    """给每个请求绑定 trace_id，并在响应头回写。

    访问日志单独记一行「方法 路径 状态 耗时」：uvicorn 的 access log 不认
    trace_id，这行才是按 id 检索时的起点。
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        token = bind_trace_id(incoming or new_trace_id())
        trace_id = current_trace_id()
        started = time.perf_counter()
        path = request.url.path
        record = path != "/metrics"
        if record:
            metrics.add_gauge("http_requests_in_flight", 1)
        try:
            response = await call_next(request)
        except Exception:
            cost_ms = (time.perf_counter() - started) * 1000
            logger.exception("%s %s 异常 耗时%.0fms",
                             request.method, request.url.path, cost_ms)
            reset_trace_id(token)
            raise
        cost_ms = (time.perf_counter() - started) * 1000
        if record:
            metrics.add_gauge("http_requests_in_flight", -1)
            labels = {"method": request.method,
                      "path": metrics.normalize_path(path),
                      "status": str(response.status_code)}
            metrics.inc("http_requests_total", labels)
            metrics.observe("http_request_duration_seconds",
                            cost_ms / 1000, {"path": labels["path"]})
        # 健康检查每 15 秒一次，进日志只会把真正的问题埋掉
        if path != "/health":
            logger.info("%s %s -> %s 耗时%.0fms", request.method,
                        path, response.status_code, cost_ms)
        response.headers["X-Request-Id"] = trace_id
        reset_trace_id(token)
        return response
