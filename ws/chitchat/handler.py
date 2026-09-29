import logging
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm
from ws.utils.llm_errors import as_chat_service_error

logger = logging.getLogger("ws.chitchat")

# 相同问题回复的缓存有效期（秒）
_CACHE_TTL = 60.0


class ChitchatHandler:
    def __init__(self):
        # key: 用户文本 -> (过期时间戳 monotonic, 回复文本)
        # 局限：进程内缓存、不区分用户与历史上下文，仅用于短时间内重复的
        # 相同问候；只缓存闲聊，TTL 很短，避免答非所问。
        self._cache: dict[str, tuple[float, str]] = {}

    async def handle(self,
                     state: DialogueState,
                     user_message: UserMessage) -> list[BotMessage]:
        prompt_text = load_prompt("chitchat_respond")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")
        chain = prompt | llm | StrOutputParser()

        key = user_message.text.strip()
        cached = self._get_cached(key)
        if cached is not None:
            logger.info("Chitchat cache hit")
            return [BotMessage(text=cached)]

        try:
            result = await chain.ainvoke({
                "user_message":
                    HistoryBuilder.render_user_message(user_message),
                "history" : HistoryBuilder.build_session(
                    state.share.sessions[-1])
            })
        except Exception as exc:
            raise as_chat_service_error(exc)

        self._put_cache(key, result)
        return [BotMessage(text=result)]

    async def stream(self,
                     state: DialogueState,
                     user_message: UserMessage):
        prompt_text = load_prompt("chitchat_respond")
        prompt = PromptTemplate.from_template(
            prompt_text, template_format="jinja2")
        chain = prompt | llm | StrOutputParser()

        key = user_message.text.strip()
        cached = self._get_cached(key)
        if cached is not None:
            logger.info("Chitchat cache hit (stream)")
            yield cached
            return

        parts: list[str] = []
        try:
            async for delta in chain.astream({
                "user_message":
                    HistoryBuilder.render_user_message(user_message),
                "history" : HistoryBuilder.build_session(
                    state.share.sessions[-1])
            }):
                parts.append(delta)
                yield delta
        except Exception as exc:
            raise as_chat_service_error(exc)

        self._put_cache(key, "".join(parts))

    def _get_cached(self, key: str) -> str | None:
        item = self._cache.get(key)
        if item is None:
            return None
        expires_at, text = item
        if time.monotonic() > expires_at:
            self._cache.pop(key, None)
            return None
        return text

    def _put_cache(self, key: str, text: str) -> None:
        if text:
            self._cache[key] = (time.monotonic() + _CACHE_TTL, text)
