from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm

class ChitchatHandler:
    async def handle(self,
                     state:DialogueState,
                     user_message: UserMessage,
                     ) -> list[BotMessage]:
        #加载提示词模板
        prompt_text = load_prompt('chitchat_respond')
        prompt= PromptTemplate.from_template(
            prompt_text,template_format="jinja2"
        )

        #构建调用链
        chain =prompt | llm | StrOutputParser()
        #调用
        result=await chain.ainvoke(input={
            "user_message":HistoryBuilder.render_user_message(user_message),
            "history" : HistoryBuilder.build(state.share.sessions[-1].turns)
        })
        return [BotMessage(text=result)]

    # 流式版本：逐段 yield 文本增量
    async def stream(self,
                     state:DialogueState,
                     user_message: UserMessage):
        prompt_text = load_prompt('chitchat_respond')
        prompt= PromptTemplate.from_template(
            prompt_text,template_format="jinja2"
        )
        chain =prompt | llm | StrOutputParser()
        async for delta in chain.astream(input={
            "user_message":HistoryBuilder.render_user_message(user_message),
            "history" : HistoryBuilder.build(state.share.sessions[-1].turns)
        }):
            yield delta