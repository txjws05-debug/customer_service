"""知识检索（RAG）单测。

刻意**不依赖数据库**：CI 里没有 postgres。这里覆盖可以纯逻辑验证的部分——
向量化、语料校验、查询拼接、命中过滤与降级行为；pgvector 的 SQL 由启动流程
和线上验证负责。
"""

import asyncio
import math

import pytest

from ws.domain.message import MessageType, UserMessage
from ws.domain.state import DialogueState, SharedState, Turn
from ws.knowledge import provider as provider_module
from ws.knowledge import store
from ws.knowledge.corpus import KnowledgeDoc, corpus_hash, load_corpus
from ws.knowledge.embedding import (
    HashingEmbedding,
    OpenAICompatEmbedding,
    build_embedding_backend,
    extract_features,
    l2_normalize,
)


def _message(text: str) -> UserMessage:
    return UserMessage(
        sender_id="u1", message_id="m1",
        type=MessageType.TEXT, text=text)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


# ---------------------------------------------------------------- 向量化

def test_extract_features_covers_cjk_bigram_and_latin():
    features = dict(extract_features("退款 refund 123"))
    assert "退" in features          # 中文单字
    assert "退款" in features        # 中文相邻二元
    assert "refund" in features      # 拉丁词整体
    assert "123" in features


def test_extract_features_ignores_punctuation_only_text():
    assert extract_features("") == []
    assert extract_features("！？—— ，。") == []


def test_hashing_embedding_is_normalized_and_stable():
    backend = HashingEmbedding(dim=128)
    first = backend.embed_text("退款多久到账")
    second = backend.embed_text("退款多久到账")

    assert first == second, "同样的文本必须得到同样的向量"
    assert len(first) == 128
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)


def test_hashing_embedding_ranks_related_text_above_unrelated():
    backend = HashingEmbedding(dim=512)
    query = backend.embed_text("退款多久能到账")
    related = backend.embed_text("退款审核通过后，款项按原支付路径退回，一般 1-3 个工作日到账。")
    unrelated = backend.embed_text("怎么开电子发票，需要提供税号吗")

    assert _cosine(query, related) > _cosine(query, unrelated)


def test_l2_normalize_keeps_zero_vector():
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_embedding_backend_factory_prefers_api_when_configured(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "embedding_base_url",
                        "https://api.example.com/v1")
    monkeypatch.setattr(provider_module.settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(provider_module.settings, "embedding_api_key", "sk-x")
    monkeypatch.setattr(provider_module.settings, "embedding_dim", 1024)

    backend = build_embedding_backend()
    assert isinstance(backend, OpenAICompatEmbedding)
    assert backend.dim == 1024
    assert backend.base_url == "https://api.example.com/v1"


def test_embedding_backend_factory_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "embedding_base_url", None)
    monkeypatch.setattr(provider_module.settings, "embedding_model", None)
    monkeypatch.setattr(provider_module.settings, "embedding_dim", 256)

    backend = build_embedding_backend()
    assert isinstance(backend, HashingEmbedding)
    assert backend.dim == 256
    assert backend.name == "local-hashing-256"


# ---------------------------------------------------------------- 语料

def test_corpus_is_well_formed():
    docs = load_corpus()
    assert len(docs) >= 10, "语料太少，检索没有意义"

    ids = [doc.doc_id for doc in docs]
    assert len(ids) == len(set(ids)), "doc_id 必须唯一"
    assert {doc.kind for doc in docs} == {"faq", "policy"}

    for doc in docs:
        assert doc.title.strip()
        assert doc.content.strip()


def test_embedding_text_repeats_title_and_includes_aliases():
    doc = KnowledgeDoc(doc_id="d1", kind="faq", title="退款多久到账",
                       content="1-3 个工作日", source="售后",
                       aliases="钱什么时候退回来")
    assert doc.embedding_text.count("退款多久到账") == 2
    assert "1-3 个工作日" in doc.embedding_text
    assert "钱什么时候退回来" in doc.embedding_text


def test_corpus_has_alias_expansion_for_faq():
    docs = [doc for doc in load_corpus() if doc.kind == "faq"]
    with_aliases = [doc for doc in docs if doc.aliases]
    assert len(with_aliases) >= len(docs) // 2, "口语化别名是召回的主要手段，不能缺失"


def test_corpus_hash_tracks_content_changes():
    base = [KnowledgeDoc("d1", "faq", "标题", "内容", "来源")]
    same = [KnowledgeDoc("d1", "faq", "标题", "内容", "来源")]
    changed = [KnowledgeDoc("d1", "faq", "标题", "改过的内容", "来源")]

    assert corpus_hash(base) == corpus_hash(same)
    assert corpus_hash(base) != corpus_hash(changed)


# ---------------------------------------------------------------- 检索查询拼接

def test_build_query_text_keeps_long_question_as_is():
    state = DialogueState(sender_id="u1")
    text = "这个订单的退款大概要多久才能到账"
    assert provider_module.build_query_text(_message(text), state) == text


def test_build_query_text_expands_short_follow_up():
    shared = SharedState()
    shared.create_session()
    shared.sessions[-1].turns.append(Turn(
        turn_id="t1",
        user_message=_message("退款多久到账"),
    ))
    state = DialogueState(sender_id="u1", share=shared)

    query = provider_module.build_query_text(_message("那要多久"), state)
    assert "退款多久到账" in query
    assert "那要多久" in query


def test_build_query_text_without_history_still_works():
    state = DialogueState(sender_id="u1")
    assert provider_module.build_query_text(_message("那要多久"), state) == "那要多久"


# ---------------------------------------------------------------- provider

def test_providers_scope_retrieval_by_kind():
    assert provider_module.FAQProvider().kinds == ("faq",)
    assert provider_module.RAGProvider().kinds == ("policy",)


def _hit(doc_id: str, score: float) -> store.SearchHit:
    return store.SearchHit(
        doc_id=doc_id, kind="faq", title=f"标题-{doc_id}", content=f"内容-{doc_id}",
        source="售后服务规则", score=score, vector_score=score, keyword_score=0.0)


def _patch_retrieval(monkeypatch, hits, captured: dict | None = None):
    class FakeBackend:
        name = "fake"
        dim = 4

        async def embed(self, texts):
            return [[0.25] * 4 for _ in texts]

    monkeypatch.setattr(provider_module, "get_embedding_backend", lambda: FakeBackend())

    async def fake_search(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return hits

    monkeypatch.setattr(store, "search", fake_search)


def test_retrieve_returns_hits_above_threshold(monkeypatch):
    captured: dict = {}
    _patch_retrieval(monkeypatch, [_hit("d1", 0.9), _hit("d2", 0.01)], captured)

    chunks = asyncio.run(
        provider_module.FAQProvider().retrieve(_message("退款多久到账"),
                                              DialogueState(sender_id="u1")))

    assert len(chunks) == 1, "低于阈值的候选必须被过滤掉"
    assert "标题-d1" in chunks[0].content
    assert "内容-d1" in chunks[0].content
    assert captured["kinds"] == ["faq"], "FAQ 只检索 faq"
    assert captured["query_text"] == "退款多久到账"


def test_retrieve_returns_hint_when_nothing_matches(monkeypatch):
    _patch_retrieval(monkeypatch, [_hit("d1", 0.001)])

    chunks = asyncio.run(
        provider_module.RAGProvider().retrieve(_message("随便问问"),
                                              DialogueState(sender_id="u1")))

    assert chunks[0].content == "未检索到相关信息"


def test_retrieve_degrades_gracefully_when_search_fails(monkeypatch):
    class FakeBackend:
        name = "fake"
        dim = 4

        async def embed(self, texts):
            return [[0.25] * 4 for _ in texts]

    monkeypatch.setattr(provider_module, "get_embedding_backend", lambda: FakeBackend())

    async def boom(**kwargs):
        raise RuntimeError("数据库挂了")

    monkeypatch.setattr(store, "search", boom)

    # 检索失败不能把整轮对话炸掉，应回退成“没检索到”
    chunks = asyncio.run(
        provider_module.FAQProvider().retrieve(_message("退款多久到账"),
                                              DialogueState(sender_id="u1")))
    assert chunks[0].content == "未检索到相关问题"


def test_vector_literal_matches_pgvector_format():
    assert store.vector_literal([0.5, -1.0]) == "[0.500000,-1.000000]"


@pytest.mark.parametrize("text", ["退款", "发票", "物流", "优惠券"])
def test_local_vectors_are_not_all_identical(text):
    backend = HashingEmbedding(dim=64)
    assert any(abs(value) > 0 for value in backend.embed_text(text))
