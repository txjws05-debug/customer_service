from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import BotMessage, UserMessage
from ws.domain.state import Turn
from ws.knowledge.intents import KnowledgeIntent
from ws.knowledge.provider import KnowledgeChunk
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm

#把查询得到的答案，提交llm，由llm整理后返回最终答案
class KnowledgeResponder:
    #provider查询答案 chunks：list[KnowledgeChunk]
    #user_message
    #turns 历史记录
    async def respond(self,
                     chunks: list[KnowledgeChunk],
                     user_message: UserMessage,
                     turns:list[Turn]) -> BotMessage:
        # 加载提示词模板
        prompt_text= load_prompt("knowledge_respond")
        prompt=PromptTemplate.from_template(
            prompt_text,template_format="jinja2",
        )
        #调用链
        chain=prompt | llm| StrOutputParser()
        #调用方法
        result = await chain.ainvoke(input={
            "user_message": HistoryBuilder.render_user_message(user_message),
            "history":HistoryBuilder.build(turns),
            "knowledge_content":'\n'.join(
                [
                    chunk.content
                    for chunk in chunks
                ])

        })
        return BotMessage(text=result)

    # 流式版本：基于检索到的 chunks，逐段 yield LLM 整理结果
    async def stream(self,
                     chunks: list[KnowledgeChunk],
                     user_message: UserMessage,
                     turns:list[Turn]):
        prompt_text= load_prompt("knowledge_respond")
        prompt=PromptTemplate.from_template(
            prompt_text,template_format="jinja2",
        )
        chain=prompt | llm| StrOutputParser()
        async for delta in chain.astream(input={
            "user_message": HistoryBuilder.render_user_message(user_message),
            "history":HistoryBuilder.build(turns),
            "knowledge_content":'\n'.join(
                [chunk.content for chunk in chunks])
        }):
            yield delta