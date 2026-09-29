from dataclasses import  dataclass,field

#定义知识检索，范围，不同范围对应答案位置
#1 封装知识检索数据

@dataclass
class KnowledgeIntent:
    id :str #意图识别值  product_info
    description: str #llm更好理解id含义“商品信息咨询”
    #问题答案位置provider类里面属性值对应
    provider_ids:list[str]=field(default_factory=list)
    #规则：查询商品、订单 信息都需要从对象获取值
    requires_object: str| None=None
#2创建字典 product_info
KNOWLEDGE_INTENTS :dict[str,KnowledgeIntent]={
    "product_info": KnowledgeIntent(
        id ="product_info",description="商品信息咨询",
        provider_ids=["api.product"],requires_object="product",
    ),
    "order_info": KnowledgeIntent(
        id="order_info",description="订单信息咨询",
        provider_ids=['api.order'],requires_object="object",
    ),
    "refund_policy":KnowledgeIntent(
        id="refund_policy",description="退款政策咨询",
        provider_ids=["faq.default","rag.default"],
    ),
    "return_policy":KnowledgeIntent(
        id="return_policy",description="退货政策咨询",
        provider_ids=["faq.default","rag.default"],
    ),
    "shipping_policy": KnowledgeIntent(
        id="shipping_policy", description="配送政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "platform_rule": KnowledgeIntent(
        id="platform_rule", description="平台规则咨询",
        provider_ids=["rag.default"],
    ),
    "general_ecommerce_info": KnowledgeIntent(
        id="general_ecommerce_info", description="电商通用信息咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
}