"""人工工单接口。

两条使用路径：
- 用户侧：`GET /api/handoff/status` 查自己有没有在排队的工单；
- 运营侧：`/pending`、`/{id}/take`、`/{id}/close`，用 `X-Operator-Token` 保护。

运营令牌为空时一律 403 —— 宁可接口不可用，也不能默认敞开：
队列里有用户 id 和最后一条消息，属于用户数据。
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from ws.api.deps import get_current_user, get_handoff_repository
from ws.config.config import settings
from ws.repository.handoff_repository import HandoffRepository

router = APIRouter(prefix="/api/handoff", tags=["人工接管"])


def require_operator(x_operator_token: str | None = Header(default=None)) -> str:
    expected = settings.operator_token
    if not expected:
        raise HTTPException(status_code=403, detail="未配置运营令牌，人工队列接口已关闭")
    if not hmac.compare_digest((x_operator_token or "").encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="运营令牌无效")
    return "operator"


def _ticket_to_dict(record) -> dict:
    return {
        "ticket_id": record.id,
        "sender_id": record.sender_id,
        "status": record.status,
        "reason": record.reason,
        "last_message": record.last_message,
        "operator": record.operator,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/status")
async def my_status(current_user: str = Depends(get_current_user),
                    repo: HandoffRepository = Depends(get_handoff_repository)):
    """用户查自己当前工单状态；没有工单时 status 为 none。"""
    record = await repo.get_open(current_user)
    if record is None:
        return {"code": 0, "data": {"status": "none"}}
    return {"code": 0, "data": _ticket_to_dict(record)}


@router.get("/pending")
async def list_pending(repo: HandoffRepository = Depends(get_handoff_repository),
                       operator: str = Depends(require_operator)):
    records = await repo.list_pending()
    return {"code": 0, "data": {"total": len(records),
                                "items": [_ticket_to_dict(r) for r in records]}}


@router.post("/{ticket_id}/take")
async def take(ticket_id: str,
               repo: HandoffRepository = Depends(get_handoff_repository),
               operator: str = Depends(require_operator)):
    record = await repo.take(ticket_id, operator="operator")
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在或已被接手")
    return {"code": 0, "data": _ticket_to_dict(record)}


@router.post("/{ticket_id}/close")
async def close(ticket_id: str,
                repo: HandoffRepository = Depends(get_handoff_repository),
                operator: str = Depends(require_operator)):
    record = await repo.close(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在或已关闭")
    return {"code": 0, "data": _ticket_to_dict(record)}
