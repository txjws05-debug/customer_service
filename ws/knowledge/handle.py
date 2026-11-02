import logging

from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.knowledge.intents import KnowledgeIntent, KNOWLEDGE_INTENTS

# 未知意图时退回的通用知识库。宁可检索得宽一点，也不要 500。
DEFAULT_PROVIDER_ID = "faq.default"

logger = logging.getLogger(__name__)
from ws.knowledge.provider import KnowledgeProvider, KnowledgeChunk
from ws.knowledge.registry import KnowledgeProviderRegistry
from ws.knowledge.responder import KnowledgeResponder
from ws.prompts.history_builder import HistoryBuilder

#对外调用方法，负责处理知识检索过程
class KnowledgeHandler:
    def __init__(self,
                 knowledge_intents: dict[str,KnowledgeIntent],
                 provider_registry: KnowledgeProviderRegistry,
                 knowledge_responder: KnowledgeResponder):
        self.knowledge_intents =knowledge_intents
        self.provider_registry=provider_registry
        self.knowledge_responder=knowledge_responder
    #意图识别结果["return_policy","product_info"]
    #2 user_message
    #3 state
    async def handle(self,
                     knowledge_intents: list[str],
                     user_message: UserMessage,
                     state:DialogueState,)->list[BotMessage]:
        #1获取上一把=步意图识别结果
        #2 根据意图识别结果找到答案位置
        provider_ids:list[str]=self.get_provider_ids(knowledge_intents)
        #3根据上一步找到答案位置，根据位置找到对应provider对象
        ##把位置list遍历，得到每个位置名称，根据每个位置名称找到对应provide对象
        #["faq.default", "rag.default" , "api.product"]
        final_result:list[KnowledgeChunk]=[]
        for provider_id in provider_ids:
            provider_obj=self.provider_registry.get(provider_id)
            #4把对应provider对象的方法执行得到结果
            result=await provider_obj.retrieve(
                state=state,
                user_message=user_message,
            )
            final_result.extend(result)
        # 把provider对象的方法执行得到结果提交llm，整理返回最终答案
        response = await self.knowledge_responder.respond(
            chunks=final_result,
            user_message=user_message,
            history=HistoryBuilder.build_session(
                state.share.sessions[-1]),
        )
        return [response]
    # 流式版本：检索完成后，逐段 yield LLM 整理的最终答案
    async def stream(self,
                     knowledge_intents: list[str],
                     user_message: UserMessage,
                     state:DialogueState):
        provider_ids:list[str]=self.get_provider_ids(knowledge_intents)
        final_result:list[KnowledgeChunk]=[]
        for provider_id in provider_ids:
            provider_obj=self.provider_registry.get(provider_id)
            result=await provider_obj.retrieve(
                state=state,
                user_message=user_message,
            )
            final_result.extend(result)
        async for delta in self.knowledge_responder.stream(
            chunks=final_result,
            user_message=user_message,
            history=HistoryBuilder.build_session(
                state.share.sessions[-1]),
        ):
            yield delta
    #根据意图识别结果找到答案位置 并去重
    def get_provider_ids(self,knowledge_intents:list[str])->list[str]:
        final_provider_ids: list[str] = []
        #遍历得到每个意图识别结果值
        for intent in knowledge_intents:
            # 拿意图识别结果到字典找位置。
            # 用 get 而不是下标：模型偶尔会编出枚举里没有的名字
            #（例如「能退差价吗」被识别成 price_difference_refund_policy），
            # 下标写法会把一次正常的业务提问变成 500 —— 靠运气不触发的崩溃最难查。
            entry = KNOWLEDGE_INTENTS.get(intent)
            if entry is None:
                logger.warning("未知知识意图 %r，按通用知识检索处理", intent)
                final_provider_ids.append(DEFAULT_PROVIDER_ID)
                continue
            final_provider_ids.extend(entry.provider_ids)
        # final_provider_ids去重 ["faq.default", "faq.default" , "api.product"]
        # 第一种 set集合， 缺陷：无法保证数据顺序
        return list(set(final_provider_ids))

        # 第二种 dict方法 dict.fromkeys()，优点：保证数据顺序
        # return list(dict.fromkeys(final_provider_ids))