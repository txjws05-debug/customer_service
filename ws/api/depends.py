from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ws.engine.dialogue_engine import DialogueEngine
from ws.repository.dialogue_repository import DialogueRepository
from ws.service.dialogue_service import DialogueService
from ws.utils import database

async def get_session():
    async with database.async_session() as session:
        yield session

async def get_dialogue_engine():
    return DialogueEngine()

async def get_dialogue_repository(session: AsyncSession=Depends(get_session)):
    return DialogueRepository(session=session)

async def get_dialogue_service(
        dialogue_repository:DialogueRepository=Depends(get_dialogue_repository),
        dialogue_engine:DialogueEngine=Depends(get_dialogue_engine)):


    return DialogueService(dialogue_repository=dialogue_repository,dialogue_engine=dialogue_engine)


