import asyncio

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession, result

from ws.domain.state import DialogueState
from ws.repository.orm.dialogue_state import DialogueStateRecord
from ws.utils import database
from ws.utils.database import close_engine, init_db_engine


# TypeAdapter类型适配器
# 方便进行 序列化 和 反序列化操作
# 对象 =》 json字符串   dump_json
# json字符串 =》 对象   validate_json
DIALOGUE_STATE_ADAPTER=TypeAdapter(DialogueState)
# 操作数据库
class DialogueRepository:
    def __int__(self,session: AsyncSession):
        self.session = session
        #根据sender_id 查询历史会话信息状态数据
        #因为只存储上一次会话状态记录数据，查询结果为空/有一条记录
    async def load(self,sender_id:str) -> DialogueState:
        sql=select(DialogueStateRecord).where(
            DialogueStateRecord.sender_di==
            sender_id
        )

        result=await self.session.execute(sql)
        record=result.scalar_one_or_none()
        if record:
            #转化为DialogueState
            state=DIALOGUE_STATE_ADAPTER.validate_json(record.state_json)
            return state
        else:
            return DialogueState(sender_id=sender_id)

    #保存会话状态数据
    async def save(self,state:DialogueState):
        # 1 把DialogueState对象类型数据转换字符串
        state_json=DIALOGUE_STATE_ADAPTER.dump_json(state).decode(encoding='utf-8')
        # 2 创建sql语句
        # from sqlalchemy.dialects.mysql import insert
        statement=insert(DialogueStateRecord).values(
            sender_id=state.sender_id,
            state_json=state_json
        )
        on_duplicate_key=statement.on_duplicate_key_update(
            state_json=state_json
        )
        await self.session.execute(on_duplicate_key)
        await self.session.commit()

if __name__=='__main__':
    init_db_engine()
    async def test():
        async with database.async_session()as session:
            dialogueRepository=DialogueRepository(session)
            #
            state=await dialogueRepository.load(sender_id='1')
            print(state)
        await close_engine()
    asyncio.run(test())