# -*- coding: utf-8 -*-
"""未知知识意图不能把请求打成 500。

背景：评测里「刚买完就降价了，能退差价吗」稳定 500，
因为模型输出意图 price_difference_refund_policy，而枚举里没有这个名字，
get_provider_ids 用下标取值直接 KeyError。
同义的「价保怎么申请」却正常 —— 这是靠运气不触发的崩溃，必须用测试钉死。
"""
from ws.knowledge.handle import DEFAULT_PROVIDER_ID, KnowledgeHandler


def _provider_ids(intents):
    # 只测纯函数逻辑，不构造完整 handler 依赖
    return KnowledgeHandler.get_provider_ids.__get__(object(), object)(intents)


def test_unknown_intent_falls_back():
    """枚举里没有的意图名，退回通用知识库，而不是抛 KeyError。"""
    handler = object.__new__(KnowledgeHandler)
    ids = handler.get_provider_ids(["price_difference_refund_policy"])
    assert DEFAULT_PROVIDER_ID in ids


def test_known_intent_unchanged():
    """已知意图的行为不能被兜底逻辑改掉。"""
    handler = object.__new__(KnowledgeHandler)
    from ws.knowledge.intents import KNOWLEDGE_INTENTS
    ids = handler.get_provider_ids(["product_info"])
    assert set(ids) == set(KNOWLEDGE_INTENTS["product_info"].provider_ids)


def test_mixed_intents():
    """已知 + 未知混在一起，已知的仍要生效。"""
    handler = object.__new__(KnowledgeHandler)
    from ws.knowledge.intents import KNOWLEDGE_INTENTS
    ids = handler.get_provider_ids(["product_info", "no_such_intent"])
    for pid in KNOWLEDGE_INTENTS["product_info"].provider_ids:
        assert pid in ids
    assert DEFAULT_PROVIDER_ID in ids
