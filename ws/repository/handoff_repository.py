"""人工工单仓储。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ws.repository.orm.handoff import HandoffTicketRecord

OPEN_STATUSES = ("pending", "taken")


def _now() -> datetime:
    # 与项目其它表保持一致：存 naive UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


class HandoffRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_open(self, sender_id: str) -> HandoffTicketRecord | None:
        """取该用户未结束的工单：已有单就不再重复建，避免刷屏建出几十条。"""
        result = await self.session.execute(
            select(HandoffTicketRecord)
            .where(HandoffTicketRecord.sender_id == sender_id,
                   HandoffTicketRecord.status.in_(OPEN_STATUSES))
            .order_by(HandoffTicketRecord.created_at.desc())
            .limit(1))
        return result.scalar_one_or_none()

    async def create(self, sender_id: str, reason: str,
                     last_message: str | None) -> HandoffTicketRecord:
        existing = await self.get_open(sender_id)
        if existing is not None:
            return existing
        record = HandoffTicketRecord(
            id=str(uuid.uuid4()), sender_id=sender_id, status="pending",
            reason=reason, last_message=last_message, created_at=_now())
        self.session.add(record)
        await self.session.commit()
        return record

    async def touch(self, sender_id: str, last_message: str | None) -> None:
        """用户又说话了：更新最后一次内容，让运营接手前能看到上下文。"""
        record = await self.get_open(sender_id)
        if record is None:
            return
        record.last_message = last_message
        await self.session.commit()

    async def list_pending(self, limit: int = 50) -> list[HandoffTicketRecord]:
        result = await self.session.execute(
            select(HandoffTicketRecord)
            .where(HandoffTicketRecord.status == "pending")
            .order_by(HandoffTicketRecord.created_at.asc())
            .limit(limit))
        return list(result.scalars().all())

    async def take(self, ticket_id: str, operator: str) -> HandoffTicketRecord | None:
        record = await self.session.get(HandoffTicketRecord, ticket_id)
        if record is None or record.status != "pending":
            return None
        record.status = "taken"
        record.operator = operator
        record.taken_at = _now()
        await self.session.commit()
        return record

    async def close(self, ticket_id: str) -> HandoffTicketRecord | None:
        record = await self.session.get(HandoffTicketRecord, ticket_id)
        if record is None or record.status == "closed":
            return None
        record.status = "closed"
        record.closed_at = _now()
        await self.session.commit()
        return record
