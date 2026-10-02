import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ws.config.config import settings
from ws.domain.message import UserMessage
from ws.domain.state import DialogueState
from ws.knowledge import store
from ws.knowledge.corpus import KIND_FAQ, KIND_POLICY
from ws.knowledge.embedding import get_embedding_backend
from ws.utils.errors import ChatServiceError
from ws.utils.http import get_api_data

logger = logging.getLogger("ws.knowledge.provider")

# 短问句（多半是追问，例如“那要多久”）单独检索容易啥也命中不了，
# 把上一句用户话一起带上再检索。
_SHORT_QUERY_LEN = 10


# 调用方法得到答案
# 1 封装最终结果的类
@dataclass
class KnowledgeChunk:
    content: str = ""


# 2 编写provider基类
class KnowledgeProvider(ABC):
    provider_id: str = ""

    @abstractmethod
    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        pass


# 商品信息咨询 api.product
class ApiProductProvider(KnowledgeProvider):
    provider_id = "api.product"

    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        # 设计：页面中直接发送商品类型对象，执行当前这条线
        focused = state.share.focuse_object
        if focused is None:
            raise ChatServiceError(
                "请先在页面选择要咨询的商品，再向我提问。")

        data = await get_api_data(
            f"{settings.commerce_api_base_url}/products/{focused.id}")

        chunk = json.dumps(data, ensure_ascii=False)
        return [KnowledgeChunk(content=chunk)]


# 订单信息 api.order
class ApiOrderProvider(KnowledgeProvider):
    provider_id = "api.order"

    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        focused = state.share.focuse_object
        if focused is None:
            raise ChatServiceError(
                "请先在页面选择要咨询的订单，再向我提问。")

        # 调用查询订单详情接口
        order_url = (f"{settings.commerce_api_base_url}"
                     f"/orders/{focused.id}")
        # 调用查询订单物流接口
        logis_url = (f"{settings.commerce_api_base_url}"
                     f"/orders/{focused.id}/logistics")

        order_detail, logis_detail = await asyncio.gather(
            get_api_data(order_url),
            get_api_data(logis_url),
        )

        chunk = json.dumps({
            "order_detail": order_detail,
            "logis_detail": logis_detail,
        }, ensure_ascii=False)
        return [KnowledgeChunk(content=chunk)]


def build_query_text(user_message: UserMessage,
                     state: DialogueState) -> str:
    """拼出用于向量检索的查询文本。"""
    text = (user_message.text or "").strip()
    if len(text) >= _SHORT_QUERY_LEN:
        return text

    # 追问场景：补上最近一句用户消息
    previous = _recent_user_texts(state, exclude=text, limit=1)
    return " ".join(previous + [text]).strip() if previous else text


def _recent_user_texts(state: DialogueState, exclude: str,
                       limit: int = 1) -> list[str]:
    """从会话历史里倒着找最近的用户消息（跳过与当前重复的那句）。"""
    sessions = getattr(state.share, "sessions", None) or []
    if not sessions:
        return []

    texts: list[str] = []
    for turn in reversed(sessions[-1].turns):
        candidate = (getattr(turn.user_message, "text", "") or "").strip()
        if not candidate or candidate == exclude or candidate in texts:
            continue
        texts.append(candidate)
        if len(texts) >= limit:
            break
    return list(reversed(texts))


class VectorKnowledgeProvider(KnowledgeProvider):
    """基于 pgvector 的知识检索：把问题向量化，再做混合检索。

    子类只需要声明检索哪些 kind（faq / policy），以及检索不到时的兜底话术。
    """

    #: 参与检索的知识类型
    kinds: tuple[str, ...] = ()
    #: 一条都没命中时返回给 LLM 的说明
    empty_hint: str = "未检索到相关信息"

    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        query_text = build_query_text(user_message, state)
        if not query_text:
            return [KnowledgeChunk(content=self.empty_hint)]

        try:
            backend = get_embedding_backend()
            query_vector = (await backend.embed([query_text]))[0]
            hits = await store.search(
                query_vector=query_vector,
                query_text=query_text,
                kinds=list(self.kinds),
            )
        except Exception:  # noqa: BLE001
            # 检索失败不应该让整轮对话 500：记完整堆栈，然后回退成“没检索到”，
            # 由 LLM 按提示词如实告知用户信息不足。
            logger.exception("知识检索失败 provider=%s", self.provider_id)
            return [KnowledgeChunk(content=self.empty_hint)]

        useful = [hit for hit in hits if hit.score >= settings.knowledge_min_score]
        if not useful:
            logger.info(
                "知识检索无有效命中 provider=%s query=%r 最高分=%s",
                self.provider_id, query_text,
                f"{hits[0].score:.3f}" if hits else "无候选")
            return [KnowledgeChunk(content=self.empty_hint)]

        logger.info(
            "知识检索命中 provider=%s query=%r -> %s",
            self.provider_id, query_text,
            ", ".join(f"{hit.doc_id}({hit.score:.3f})" for hit in useful))

        return [KnowledgeChunk(content=hit.render()) for hit in useful]


# faq：短问答类知识
class FAQProvider(VectorKnowledgeProvider):
    provider_id = 'faq.default'
    kinds = (KIND_FAQ,)
    empty_hint = "未检索到相关问题"


# rag：规则条款类知识
class RAGProvider(VectorKnowledgeProvider):
    provider_id = 'rag.default'
    kinds = (KIND_POLICY,)
    empty_hint = "未检索到相关信息"
