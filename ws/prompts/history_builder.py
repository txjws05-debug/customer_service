import json
from dataclasses import asdict

from ws.domain.message import UserMessage, MessageType, BotMessage
from ws.domain.state import Turn, Session


class HistoryBuilder:
    @staticmethod
    def build(turns: list[Turn],
              summary: str = "",
              skip: int = 0) -> str:
        messages: list[str] = []

        # 旧历史已被压缩成摘要
        if summary:
            messages.append(f"SUMMARY:{summary}")

        for turn in turns[skip:]:
            user_message = HistoryBuilder.render_user_message(turn.user_message)
            messages.append(user_message)
            for bot_message in turn.bot_message:
                messages.append(
                    HistoryBuilder.render_bot_message(bot_message))
        return "\n".join(messages)

    @staticmethod
    def build_session(session: Session) -> str:
        """渲染喂给 LLM 的上下文：摘要 + 最近窗口原文。"""
        return HistoryBuilder.build(
            session.turns,
            summary=session.history_summary,
            skip=session.summarized_turn_count)

    @staticmethod
    def render_user_message(user_message: UserMessage) -> str:
        if user_message.type == MessageType.TEXT:
            return f"USER:{user_message.text}"
        return f"USER:{json.dumps(asdict(user_message.object), ensure_ascii=False)}"

    @staticmethod
    def render_bot_message(bot_message: BotMessage) -> str:
        if bot_message.text:
            return f"BOT:{bot_message.text}"
        return f"BOT:{json.dumps(asdict(bot_message.object), ensure_ascii=False)}"
