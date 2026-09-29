import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ws.config.config import settings
from ws.domain.message import UserMessage
from ws.domain.state import DialogueState
from ws.utils.errors import ChatServiceError
from ws.utils.http import get_api_data


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


# faq
class FAQProvider(KnowledgeProvider):
    provider_id = 'faq.default'

    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        # TODO
        return [KnowledgeChunk(content="未检索到相关问题")]


class RAGProvider(KnowledgeProvider):
    provider_id = 'rag.default'

    async def retrieve(self,
                       user_message: UserMessage,
                       state: DialogueState) -> list[KnowledgeChunk]:
        # RAG知识库查询知识接口
        return [KnowledgeChunk(content="未检索到相关信息")]
