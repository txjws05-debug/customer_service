from itertools import chain

from jinja2 import Template
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.prompts.history_builder import HistoryBuilder
from ws.task.response.models import ResponseTemplate, ResponseMode
from ws.utils.llm_client import llm


#数据渲染
class ResponseRender:
    #template : mode text prompt
    async def render(self,template:ResponseTemplate,
                     state:DialogueState,
                     user_message:UserMessage
                     ) -> BotMessage:
        #判断不同mode做不同的处理
        #static渲染text内容，直接返回text内容
        if template.mode==ResponseMode.STATIC:
            #jinja2 渲染
            template=Template(template.text)
            render_text=template.render(slots=state.tasks.active.slots)
            return BotMessage
        #reohrase:有text文本，调用llm，根据提示词和text文本，llm修改内容返回
        if template.mode==ResponseMode.REPHRASE:
            #text内容渲染
            render_text=Template(template.text).render(
                slots=state.tasks.active.slots
            )
        # 加载提示词模板用langchain
            prompt=PromptTemplate.from_template(template.prompt,template_format='jinja2')
            #调用llm。返回结果
            chain=prompt|llm|StrOutputParser()
            res=await chain.ainvoke(
                {
                    "history": HistoryBuilder.build(
                        state.share.sessions[-1].turns
                    ),
                    "user_message": HistoryBuilder.render_user_message(user_message),
                    "current_response": render_text
                }
            )
            #封装BotMessage
            return BotMessage(text=res)
        #generate :根据提示词，调用llm生成结果，没有text文本
        if template.mode==ResponseMode.GENERATE:
            prompt=PromptTemplate.from_template(
                template.prompt,template_format="jinja2",
            )
            chain=prompt|llm|StrOutputParser()
            res=await chain.ainvoke({
                "history": HistoryBuilder.build(
                state.share.sessions[-1].turns
            ),
            "user_message":HistoryBuilder.render_user_message(user_message)
            })
            return BotMessage(text=res)