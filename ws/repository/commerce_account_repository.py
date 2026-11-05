from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ws.repository.orm.commerce_account import CommerceAccountRecord


class CommerceAccountRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_cuid(self, username: str) -> str | None:
        return await self.session.scalar(
            select(CommerceAccountRecord.cuid)
            .where(CommerceAccountRecord.username == username))

    async def bind(self, username: str, cuid: str) -> None:
        self.session.add(CommerceAccountRecord(username=username, cuid=cuid))
        await self.session.flush()
