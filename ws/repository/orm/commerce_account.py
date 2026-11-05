from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ws.repository.orm.base import Base


class CommerceAccountRecord(Base):
    """客服账号 → 商城账号的绑定。商城号由中台开户分配，用户无从指定。"""

    __tablename__ = "commerce_accounts"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    cuid: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
