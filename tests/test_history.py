from ws.domain.message import BotMessage, MessageType, UserMessage
from ws.domain.state import SharedState, Turn
from ws.prompts.history_builder import HistoryBuilder


def _turn(user_text: str, bot_text: str) -> Turn:
    return Turn(
        turn_id="t",
        user_message=UserMessage(
            sender_id="u1", message_id="m1",
            type=MessageType.TEXT, text=user_text),
        bot_message=[BotMessage(text=bot_text)])


def test_build_plain():
    out = HistoryBuilder.build([_turn("你好", "您好")])
    assert "USER:你好" in out
    assert "BOT:您好" in out


def test_build_session_with_summary_and_skip():
    shared = SharedState()
    shared.create_session()
    session = shared.sessions[-1]
    session.turns.extend([
        _turn("旧问题1", "旧回答1"),
        _turn("旧问题2", "旧回答2"),
        _turn("新问题", "新回答"),
    ])
    session.history_summary = "用户之前问过物流。"
    session.summarized_turn_count = 2

    out = HistoryBuilder.build_session(session)
    assert out.startswith("SUMMARY:用户之前问过物流。")
    assert "旧问题1" not in out
    assert "旧问题2" not in out
    assert "新问题" in out
    assert "新回答" in out
