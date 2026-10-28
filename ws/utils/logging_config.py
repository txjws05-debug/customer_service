"""日志配置。

两条原则：
- 每条日志都要能回答「它属于哪次请求」，所以格式里固定带 trace_id；
- trace_id 的存储放在这里（而不是 trace.py），避免日志模块与中间件互相 import。

注意 Python logging 的约定：过滤器必须挂在 handler 上，格式串里的
%(trace_id)s 才有值；漏挂会在每条日志上抛格式化错误，表现为日志全变成
"--- Logging error ---"，而不是报错退出 —— 这个坑很容易漏。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

TRACE_FIELD = "trace_id"

# 默认 "-"：不在请求上下文里（启动、定时任务）也要有值，否则格式化失败
_trace_var: ContextVar[str] = ContextVar("trace_id", default="-")

_DEFAULT_FORMAT = (
    "%(asctime)s %(levelname)-7s [%(trace_id)s] %(name)s: %(message)s")
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def current_trace_id() -> str:
    return _trace_var.get()


def bind_trace_id(value: str | None) -> object:
    return _trace_var.set(value or "-")


def reset_trace_id(token: object) -> None:
    _trace_var.reset(token)


class TraceIdFilter(logging.Filter):
    """把当前 trace_id 补到每条日志记录上。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, TRACE_FIELD, None):
            setattr(record, TRACE_FIELD, current_trace_id())
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """统一根 logger 格式，应用启动时调用一次。

    force=True 覆盖 uvicorn / 库自身已有的 handler 配置。
    """
    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        datefmt=_DEFAULT_DATEFMT,
        force=True,
    )
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(TraceIdFilter())
    # uvicorn 的 access / error logger 有独立 handler，也要补，
    # 否则「请求进来」的那几行没有 trace_id，排障时正好断在最关键的位置
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(TraceIdFilter())
