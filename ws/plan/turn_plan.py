import json
from dataclasses import asdict

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from openai.types.conversations import conversation

from ws.domain.message import UserMessage
from ws.domain.state import DialogueState
from ws.plan.models import TurnPlan
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.task.flow.models import FlowCatalog, Flow
from ws.utils.llm_client import llm


class TurnPlan:
    async def plan(self,user_message: UserMessage,
                   state:DialogueState,
                   flow_catalog:FlowCatalog)->TurnPlan:
        #加载提示词模板
        prompt_text = load_prompt('turn_plan')
        prompt= PromptTemplate.from_template(
            prompt_text,template_format="jinja2",
        )
        #创建调用链
        chian = prompt| llm| JsonOutputParser()
        #获取提示词模板，调用ainvoke并传递到方法里面
        #用户信息
        user_message= HistoryBuilder.render_user_message(user_message)
        #历史多轮对话
        conversation_history=HistoryBuilder.build(state.share.sessions[-1].turns)
        #聚焦对象数据
        focused_object_json = json.dumps(
            asdict(state.share.focuse_object)
            if state.shared.focused_object else None,ensure_ascii=False
        )
        #task_state_json
        task_state_json= json.dumps(asdict(state.tasks)
                                    if state.tasks else None, ensure_ascii=False)
        #flows_json 流程数据
        #获取所有流程中，每个流程不包含步骤数据
        flows: dict[str,Flow] = flow_catalog.flows
        # items() k，v
        # .values()   Flow
        flows_json=[
            {k:v for k,v in asdict(flow).items()
                     if k !='steps'}
                    for flow in flows.values()
                    ]
        #调用方得到结果
        res=await chian.ainvoke({
            "flows_json": flows_json,
            "task_state_json": task_state_json,
            "focused_object_json": focused_object_json,
            "conversation_history":conversation_history,
            "user_message": user_message,
            "knowledge_intents_json" : {},
        })
        #把llm返回结果封装TrunPlan
        return  TurnPlan.from_dict(res)
    