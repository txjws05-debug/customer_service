"""人工接管：把"要不要转人工"从模型手里拿走。

三个判断都是确定性的，理由和越权拦截一样 —— 转人工意味着成本模式切换
（从按 token 计费变成真人时间），不能交给概率模型决定。

1. 用户明确要人工（关键词）；
2. 该用户已有未结束工单：不再调 LLM，只回一句"人工正在看"，省钱也避免自相矛盾；
3. 其它情况放行走 AI。
"""

from __future__ import annotations

import logging

from ws.repository.handoff_repository import HandoffRepository

logger = logging.getLogger("ws.handoff")

HUMAN_KEYWORDS = ("转人工", "人工客服", "人工服务", "找人工", "真人客服", "要人工", "接人工")

HANDOFF_REPLY = (
    "已经为你转接人工客服，工单已登记，请稍等片刻。\n\n"
    "人工客服会看到我们刚才的对话内容，不需要你重复描述。"
)
WAITING_REPLY = (
    "人工客服正在查看你的会话，请稍等一下。\n\n"
    "如果你想补充信息，直接发在这里就行，客服接手时能看到。"
)


def wants_human(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in HUMAN_KEYWORDS)


class HandoffService:
    def __init__(self, repository_getter):
        # 传 getter 而不是 session：请求级 session 由依赖注入管理生命周期
        self._repo = repository_getter

    async def intercept(self, sender_id: str, text: str | None) -> str | None:
        """返回固定话术表示已由人工通道接管；返回 None 表示继续走 AI。

        注意顺序：先看有没有未结束工单，再看关键词。
        反过来的话，用户连着说两次「转人工」会收到两次「已为你转接」，
        听起来像没生效 —— 第二次应该告诉他「已经有人在看了」。
        """
        open_ticket = await self._repo().get_open(sender_id)
        if open_ticket is not None:
            await self._repo().touch(sender_id, last_message=text)
            return WAITING_REPLY

        if wants_human(text):
            await self._repo().create(sender_id, reason="user_request", last_message=text)
            logger.info("用户 %s 请求转人工", sender_id)
            return HANDOFF_REPLY
        return None
