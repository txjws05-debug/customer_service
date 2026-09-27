import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ws.config.config import settings
from ws.domain.message import UserMessage
from ws.domain.state import DialogueState
from ws.utils.http import http_client


#调用方法得到答案
#1封装最终结果的类
@dataclass
class KnowledgeChunk:
    content:str=""

#2 编写provider基类
class KnowledgeProvider(ABC):
    provider_id: str=""
    @abstractmethod
    async def retrieve(self,
                       user_message:UserMessage,
                       state:DialogueState,)-> list[KnowledgeChunk]:
        pass

    #调用中台接口得到答案
    # 商品信息咨询 api.product
class ApiProductProvider(KnowledgeProvider):
    provider_id = "api.product"

    async  def retrieve(self,
                       user_message:UserMessage,
                       state:DialogueState,) -> list[KnowledgeChunk]:
        #设计：页面中直接发送商品类型对象，执行当前这条线
        #获取商品id
        product_id = state.share.focuse_object.id
        #调用中台接口实现
        url=(f"{settings.commerce_api_base_url}"
             f"/products/{product_id}")
        #http调用
        response = await http_client.get(url)
        #todo 完善空值处理
        data=response.json()['data']

        #knowledge
        chunk = json.dumps(data,ensure_ascii=False)
        return [KnowledgeChunk(content=chunk)]
#订单信息 api.order
class ApiOrderProvider(KnowledgeProvider):
    provider_id = "api.order"
    async def retrieve(self,
                       user_message:UserMessage,
                       state:DialogueState,) -> list[KnowledgeChunk]:
        order_id=state.share.focuse_object.id
        #得到订单信息，调用两个中台接口
        #调用查询订单详情接口
        order_url=(f"{settings.commerce_api_base_url}"
                   f"/orders/{order_id}")
        #调用查询订单物流接口
        logis_url=(f"{settings.commerce_api_base_url}"
                   f"/orders/{order_id}/logistics")

        order_info,logis_info=await asyncio.gather(
            http_client.get(order_url),
            http_client.get(logis_url),
        )
        #list[KnowledgeChunk]
        chunk = json.dumps({
            "order_detail":order_info.json()['data'],
            "logis_detail":logis_info.json()['data'],
        },ensure_ascii=False
        )
        return [KnowledgeChunk(content=chunk)]
#fag
class FAQProvider(KnowledgeProvider):
    provider_id = 'faq.default'
    async  def retrieve(self,
                       user_message:UserMessage,
                       state:DialogueState,) -> list[KnowledgeChunk]:
        #TODO
        return [KnowledgeChunk(content="未检索到相关问题")]
class RAGProvider(KnowledgeProvider):
    provider_id = 'rag.default'

    async def retrieve(self,
                       user_message:UserMessage,
                       state:DialogueState,) -> list[KnowledgeChunk]:
        #RAG知识库查询知识接口
        return [KnowledgeChunk(content="未检索到相关信息")]