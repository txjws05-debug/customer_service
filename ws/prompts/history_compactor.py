import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from ws.domain.state import Session
from ws.prompts.history_builder import HistoryBuilder
from ws.prompts.loader import load_prompt
from ws.utils.llm_client import llm

logger = logging.getLogger("ws.prompts.compactor")

# 始终保留原文的最近轮数
WINDOW_SIZE = 6
# 未摘要轮数超过该值时触发一次压缩
TRIGGER_SIZE = 10


async def maybe_compact_history(session: Session) -> None:
    """上下文过长时，把窗口之外的旧轮次交给 LLM 压缩成摘要。

    摘要与已摘要游标记录在 session 上并随状态落库；
    压缩失败不阻塞主对话（跳过，后续轮次再尝试）。
    """
    unsummarized = len(session.turns) - session.summarized_turn_count
    if unsummarized <= TRIGGER_SIZE:
        return

    cutoff = session.summarized_turn_count + (unsummarized - WINDOW_SIZE)
    old_turns = session.turns[session.summarized_turn_count:cutoff]
    old_history = HistoryBuilder.build(old_turns)

    prompt = PromptTemplate.from_template(
        load_prompt("history_summary"), template_format="jinja2")
    chain = prompt | llm | StrOutputParser()

    try:
        new_part = await chain.ainvoke({"old_history": old_history})
    except Exception as exc:
        logger.warning("History summarization skipped: %s",
                       type(exc).__name__)
        return

    session.history_summary = _merge_summary(
        session.history_summary, new_part)
    session.summarized_turn_count = cutoff
    logger.info("Compacted %d old turn(s), cutoff=%d",
                len(old_turns), cutoff)


def _merge_summary(existing: str, new_part: str) -> str:
    new_part = (new_part or "").strip()
    if not existing:
        return new_part
    if not new_part:
        return existing
    return f"{existing} {new_part}"
