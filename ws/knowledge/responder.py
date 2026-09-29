from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import BotMessage, UserMessage
from ws.knowledge.provider import KnowledgeChunk
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm
from ws.utils.llm_errors import as_chat_service_error

# 把查询得到的答案，提交llm，由llm整理后返回最终答案
class KnowledgeResponder:
    # chunks：provider 检索结果
    # history：已按窗口/摘要渲染好的上下文
    async def respond(self,
                      chunks: list[KnowledgeChunk],
                      user_message: UserMessage,
                      history: str) -> BotMessage:
        # 加载提示词模板
        prompt_text = load_prompt("knowledge_respond")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")

        # 调用链
        chain = prompt | llm | StrOutputParser()
        try:
            result = await chain.ainvoke(input={
                "user_message":
                    HistoryBuilder.render_user_message(user_message),
                "history": history,
                "knowledge_content": '\n'.join(
                    chunk.content for chunk in chunks)
            })
        except Exception as exc:
            raise as_chat_service_error(exc)
        return BotMessage(text=result)

    # 流式版本：基于检索到的 chunks，逐段 yield LLM 整理结果
    async def stream(self,
                     chunks: list[KnowledgeChunk],
                     user_message: UserMessage,
                     history: str):
        prompt_text = load_prompt("knowledge_respond")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")
        chain = prompt | llm | StrOutputParser()
        try:
            async for delta in chain.astream(input={
                "user_message":
                    HistoryBuilder.render_user_message(user_message),
                "history": history,
                "knowledge_content": '\n'.join(
                    chunk.content for chunk in chunks)
            }):
                yield delta
        except Exception as exc:
            raise as_chat_service_error(exc)
