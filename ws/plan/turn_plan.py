import json
import logging
from dataclasses import asdict

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.state import DialogueState
from ws.plan.models import TurnPlan
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.errors import ChatServiceError
from ws.utils.llm_client import llm
from ws.utils.llm_errors import as_chat_service_error

logger = logging.getLogger("ws.plan.planner")

# 解析失败时归类为这些异常 → 允许重试一次
_PARSE_ERRORS = (
    OutputParserException, json.JSONDecodeError,
    KeyError, ValueError, TypeError,
)


class TurnPlanner:
    async def plan(self,
                   *,
                   state: DialogueState,
                   user_message,
                   knowledge_intents,
                   flow_catalog) -> TurnPlan:
        # 加载提示词
        prompt_text = load_prompt("turn_plan")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")
        # JsonOutputParser 兼容纯 JSON 与 ```json 包裹的输出
        chain = prompt | llm | JsonOutputParser()

        # 准备输入（key 与 turn_plan.jinja2 变量一一对应）
        input_data = {
            "user_message":
                HistoryBuilder.render_user_message(user_message),
            "conversation_history":
                HistoryBuilder.build_session(state.share.sessions[-1]),
            "task_state_json":
                json.dumps(asdict(state.tasks),
                           ensure_ascii=False, default=str),
            "focused_object_json":
                json.dumps(asdict(state.share.focuse_object),
                           ensure_ascii=False, default=str)
                if state.share.focuse_object else "null",
            "flows_json":
                json.dumps(
                    {fid: flow.description
                     for fid, flow in flow_catalog.flows.items()},
                    ensure_ascii=False),
            "knowledge_intents_json":
                json.dumps(
                    [{"id": intent.id,
                      "description": intent.description}
                     for intent in knowledge_intents.values()],
                    ensure_ascii=False),
        }

        try:
            result = await chain.ainvoke(input_data)
            return TurnPlan.from_dict(result)
        except _PARSE_ERRORS:
            # LLM 偶发输出非法 JSON / 缺字段：原样重试一次
            logger.warning("TurnPlan parse failed, retrying once")
            try:
                result = await chain.ainvoke(input_data)
                return TurnPlan.from_dict(result)
            except _PARSE_ERRORS:
                logger.warning("TurnPlan parse failed again")
                raise ChatServiceError(
                    "我没太理解您的意思，能换个说法再描述一次吗？")
            except Exception as exc:
                if isinstance(exc, ChatServiceError):
                    raise
                raise as_chat_service_error(exc)
        except Exception as exc:
            # 限流 / 超时 / 连接等错误（llm 层已退避重试仍失败）
            if isinstance(exc, ChatServiceError):
                raise
            raise as_chat_service_error(exc)
