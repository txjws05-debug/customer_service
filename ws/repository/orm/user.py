from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ws.repository.orm.base import Base


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
