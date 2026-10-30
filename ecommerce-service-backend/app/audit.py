"""操作审计：谁、在什么时候、对什么、做了什么、结果如何。

为什么要有表而不是只打日志：日志能「看见」，但不能「检索」。追责时要回答的是
「这个运营今天改过哪些订单」，这需要按操作者 / 时间 / 路径过滤，日志文件做不到。

三条硬约束：

1. **审计失败不能影响业务** —— 独立 Session + 全捕获。最坏情况丢一条审计记录，
   绝不能让一次下单因为写日志失败而失败；
2. **只记写操作** —— GET 记进去只会把表刷满，没有审计价值；
3. **不记请求体** —— 里面有收货地址、手机号。审计表不该成为第二个 PII 仓库，
   要还原细节就用 `trace_id` 去翻对应时间段的日志。
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app import metrics, models
from app.trace import current_trace_id
from app import shop_rules as rules
from app.database import SessionLocal

logger = logging.getLogger("app.audit")

AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# 健康检查、指标这类探针不记；它们由监控负责，不属于「人的操作」
SKIP_PREFIXES = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json")


def should_audit(method: str, path: str) -> bool:
    """只有「会改变状态」的业务请求才值得记。"""
    if method.upper() not in AUDIT_METHODS:
        return False
    if not path.startswith("/shop"):
        return False
    return not path.startswith(SKIP_PREFIXES)


def action_of(method: str, path: str) -> str:
    """短标签，便于聚合统计（如「POST /shop/orders/*」一个月被调了多少次）。"""
    return f"{method.upper()} {metrics.normalize_path(path)}"


def record(*, trace_id: str, actor_kind: str, actor: str, method: str, path: str,
           status: int, duration_ms: int, ip: str | None = None) -> None:
    """写一条审计。绝不抛异常 —— 调用方不该为审计的失败负责。"""
    try:
        with SessionLocal() as session:
            session.add(models.AuditLog(
                trace_id=(trace_id or "")[:32] or None,
                actor_kind=(actor_kind or "anonymous")[:16],
                actor=(actor or "")[:64],
                method=method.upper()[:8],
                path=path[:255],
                action=action_of(method, path)[:64],
                status=int(status),
                duration_ms=int(duration_ms),
                ip=(ip or "")[:64] or None,
                created_at=rules.now(),
            ))
            session.commit()
    except Exception:  # noqa: BLE001
        metrics.inc("audit_log_write_failed_total")
        logger.warning("审计落库失败 %s %s", method, path, exc_info=True)


def list_logs(db: Session, *, actor: str | None = None, action: str | None = None,
              status: int | None = None, limit: int = 50,
              offset: int = 0) -> dict:
    """按操作者 / 动作 / 状态码过滤。运营查「谁动过什么」就靠这个。"""
    conditions = []
    if actor:
        conditions.append(models.AuditLog.actor == actor)
    if action:
        conditions.append(models.AuditLog.action == action)
    if status is not None:
        conditions.append(models.AuditLog.status == status)

    stmt = select(models.AuditLog)
    counter = select(func.count()).select_from(models.AuditLog)
    for condition in conditions:
        stmt = stmt.where(condition)
        counter = counter.where(condition)

    total = db.scalar(counter) or 0
    rows = db.scalars(
        stmt.order_by(models.AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return {
        "total": int(total),
        "items": [{
            "id": row.id,
            "trace_id": row.trace_id,
            "actor_kind": row.actor_kind,
            "actor": row.actor,
            "action": row.action,
            "method": row.method,
            "path": row.path,
            "status": row.status,
            "duration_ms": row.duration_ms,
            "ip": row.ip,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows],
    }


class AuditMiddleware(BaseHTTPMiddleware):
    """把「谁改了什么」写进库。

    必须挂在 AuthMiddleware **内层**（先 add 这个，再 add Auth），
    这样 dispatch 里拿到的 `current_context()` 才是被鉴权解析过的身份；
    挂外层的话所有记录都会变成 anonymous，审计等于白做。
    """

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if not should_audit(request.method, request.url.path):
            return response

        # 延迟导入：security 需要在本模块里记「被拒」，直接互相 import 会成环
        from app.security import current_context

        ctx = current_context()
        record(
            trace_id=current_trace_id(),
            actor_kind=ctx.kind,
            actor=ctx.subject or ctx.cuid or "",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
            ip=request.client.host if request.client else None,
        )
        return response
