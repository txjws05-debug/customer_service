import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.plan.models import ClarifyReason
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm
from ws.utils.llm_errors import as_chat_service_error

logger = logging.getLogger("ws.clarify")

# 每种澄清原因对应的一句建议回复（模板会把它改写得更自然）
_CLARIFY_MESSAGES: dict[ClarifyReason, str] = {
    ClarifyReason.MISSING_TRACK:
        "抱歉，我没太明白您的需求，能再说清楚一些吗？",
    ClarifyReason.MULTIPLE_TRACKS:
        "请一次只办理一件事，您希望先处理哪一个？",
    ClarifyReason.MISSING_TASK_COMMANDS:
        "请问您具体想办理什么业务呢？",
    ClarifyReason.MISSING_KNOWLEDGE_INTENT:
        "请问您想咨询哪方面的信息？",
    ClarifyReason.MISSING_FOCUSED_OBJECT:
        "请先在页面选择要咨询的商品或订单。",
    ClarifyReason.OBJECT_REQUIRES_INTENT:
        "请问您想查询这个对象的什么信息呢？",
    ClarifyReason.INVALID_TASK_COMMAND:
        "抱歉，这个操作我暂时无法完成，能换个说法吗？",
    ClarifyReason.UNKNOWN_KNOWLEDGE_INTENT:
        "抱歉，我没找到相关信息，能换个问法吗？",
}


# 输出反问消息
class ClarifyResponder:
    # 非流式：返回一条反问
    async def respond(self,
                      *,
                      state: DialogueState,
                      user_message: UserMessage,
                      reason: ClarifyReason) -> list[BotMessage]:
        chain = self._build_chain()
        try:
            result = await chain.ainvoke(
                self._input(state, user_message, reason))
        except Exception as exc:
            raise as_chat_service_error(exc)
        return [BotMessage(text=result)]

    # 流式：逐段 yield 反问内容
    async def stream(self,
                     *,
                     state: DialogueState,
                     user_message: UserMessage,
                     reason: ClarifyReason):
        chain = self._build_chain()
        try:
            async for delta in chain.astream(
                    self._input(state, user_message, reason)):
                yield delta
        except Exception as exc:
            raise as_chat_service_error(exc)

    def _build_chain(self):
        prompt_text = load_prompt("clarify_respond")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")
        return prompt | llm | StrOutputParser()

    def _input(self, state, user_message, reason) -> dict:
        focused = state.share.focuse_object
        focused_text = ""
        if focused:
            focused_text = (
                f"{focused.type} {focused.id}"
                f" {focused.title or ''}".rstrip())
        return {
            "reason": reason.value,
            "clarify_message":
                _CLARIFY_MESSAGES.get(
                    reason, "抱歉，我没太明白，能再说清楚一些吗？"),
            "focused_object": focused_text,
            "history": HistoryBuilder.build_session(
                state.share.sessions[-1]),
            "user_message":
                HistoryBuilder.render_user_message(user_message),
        }
