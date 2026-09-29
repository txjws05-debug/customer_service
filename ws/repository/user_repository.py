from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ws.repository.orm.user import UserRecord


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str) -> UserRecord | None:
        return await self.session.scalar(
            select(UserRecord).where(UserRecord.username == username))

    async def create(self, username: str, password_hash: str) -> UserRecord:
        record = UserRecord(username=username, password_hash=password_hash)
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record
