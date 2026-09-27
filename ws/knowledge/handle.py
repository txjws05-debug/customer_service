from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.knowledge.intents import KnowledgeIntent, KNOWLEDGE_INTENTS
from ws.knowledge.provider import KnowledgeProvider, KnowledgeChunk
from ws.knowledge.registry import KnowledgeProviderRegistry
from ws.knowledge.responder import KnowledgeResponder

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
        #把provider对象的方法执行得到结果提交llm，整理返回最终答案
        response=await self.knowledge_responder.respond(
            chunks=final_result,
            user_message=user_message,
            turns=state.share.sessions[-1].turns,
        )
        return [response]
    #根据意图识别结果找到答案位置 并去重
    def get_provider_ids(self,knowledge_intents:list[str])->list[str]:
        final_provider_ids=list[str]
        #遍历得到每个意图识别结果值
        for intent in knowledge_intents:
            # 拿着图识别结果值，到字典找到位置
            final_provider_ids.extend(KNOWLEDGE_INTENTS[intent].provider_ids)
        # final_provider_ids去重 ["faq.default", "faq.default" , "api.product"]
        # 第一种 set集合， 缺陷：无法保证数据顺序
        return list(set(final_provider_ids))

        # 第二种 dict方法 dict.fromkeys()，优点：保证数据顺序
        # return list(dict.fromkeys(final_provider_ids))