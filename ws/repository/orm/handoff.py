"""人工接管工单表。

为什么单独建表而不是塞进 dialogue_states 的 JSON：
工单要被运营按状态检索（谁在等、等了多久、谁接了），
塞进 JSON 里等于放弃索引，也放弃「人看数据库能看懂」这件事。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ws.repository.orm.base import Base


class HandoffTicketRecord(Base):
    __tablename__ = "handoff_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(255), index=True)
    # pending：用户还在等；taken：已被接手；closed：结束
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending")
    reason: Mapped[str] = mapped_column(String(64), default="user_request")
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
