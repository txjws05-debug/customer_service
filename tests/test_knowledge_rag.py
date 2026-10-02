"""知识检索（RAG）单测。

刻意**不依赖数据库**：CI 里没有 postgres。这里覆盖可以纯逻辑验证的部分——
向量化、语料校验、查询拼接、命中过滤与降级行为；pgvector 的 SQL 由启动流程
和线上验证负责。
"""

import asyncio
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ws.domain.message import MessageType, UserMessage
from ws.domain.state import DialogueState, SharedState, Turn
from ws.knowledge import embedding as embedding_module
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


def test_local_backend_defaults_to_512_when_dim_unset(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "embedding_base_url", None)
    monkeypatch.setattr(provider_module.settings, "embedding_model", None)
    monkeypatch.setattr(provider_module.settings, "embedding_dim", None)

    assert build_embedding_backend().dim == 512


def test_blank_embedding_dim_is_treated_as_auto(monkeypatch):
    """`EMBEDDING_DIM=` 这种留空写法必须当成自动探测，而不是解析失败。"""
    from ws.config.config import Settings

    monkeypatch.setenv("EMBEDDING_DIM", "")
    assert Settings().embedding_dim is None


# ------------------------------------------------- API embedding 后端

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """替掉 httpx.AsyncClient：记录请求，并按 dim 返回假向量。"""

    dim = 8
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse({
            "data": [
                {"embedding": [0.1] * self.dim, "index": index, "object": "embedding"}
                for index, _ in enumerate(json["input"])
            ],
            "model": json["model"],
            "object": "list",
        })


def _use_fake_http(monkeypatch, dim: int) -> None:
    _FakeAsyncClient.dim = dim
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(embedding_module.httpx, "AsyncClient", _FakeAsyncClient)


def test_api_backend_detects_dimension_on_first_call(monkeypatch):
    _use_fake_http(monkeypatch, dim=8)
    backend = OpenAICompatEmbedding(
        model="text-embedding-v3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-x", dim=0)

    assert backend.dim == 0, "没配 EMBEDDING_DIM 时应处于待探测状态"
    assert asyncio.run(backend.ensure_dim()) == 8
    assert backend.dim == 8, "探测结果要落到实例上，避免每次调用都多问一次"

    vectors = asyncio.run(backend.embed(["退款多久到账"]))
    assert len(vectors[0]) == 8
    assert math.isclose(sum(v * v for v in vectors[0]), 1.0, rel_tol=1e-9)

    request = _FakeAsyncClient.calls[0]
    assert request["url"].endswith("/compatible-mode/v1/embeddings")
    assert request["json"]["model"] == "text-embedding-v3"
    assert isinstance(request["json"]["input"], list)
    assert request["headers"]["Authorization"] == "Bearer sk-x"


def test_api_backend_rejects_non_ascii_key():
    """线上真实踩过：把中文占位符填进 key，httpx 会抛看不懂的编码错误。

    这里断言我们提前挡住，并给出能直接照做的提示。
    """
    placeholder = "sk-把这里换成你的真实key"
    with pytest.raises(ValueError) as excinfo:
        OpenAICompatEmbedding(
            model="text-embedding-v3",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=placeholder, dim=0)

    message = str(excinfo.value)
    assert "EMBEDDING_API_KEY" in message
    assert "非 ASCII" in message
    assert str(len(placeholder)) in message, "报错里要给出当前值长度，方便定位"


def test_api_backend_rejects_non_ascii_base_url():
    with pytest.raises(ValueError) as excinfo:
        OpenAICompatEmbedding(model="text-embedding-v3",
                              base_url="https://例子.com/v1", api_key="sk-x")
    assert "EMBEDDING_BASE_URL" in str(excinfo.value)


def test_api_backend_accepts_normal_ascii_config():
    backend = OpenAICompatEmbedding(
        model="text-embedding-v3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-1234567890abcdef", dim=0)
    assert backend.dim == 0


def test_api_backend_rejects_dimension_mismatch(monkeypatch):
    _use_fake_http(monkeypatch, dim=8)
    backend = OpenAICompatEmbedding(
        model="m", base_url="https://example.com/v1", api_key="k", dim=4)

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(backend.embed(["文本"]))

    message = str(excinfo.value)
    assert "EMBEDDING_DIM" in message, "报错要告诉用户改哪个配置"
    assert "8" in message


def test_reindex_batch_size_within_provider_limits():
    """阿里云百炼 text-embedding-v3 / v4 单次最多 10 条，超过会直接报错。"""
    from ws.knowledge import reindex

    assert reindex._BATCH_SIZE <= 10


class _FakeEmbeddingHandler(BaseHTTPRequestHandler):
    """最小可用的 OpenAI 兼容 /embeddings 服务，用于真实 HTTP 往返测试。"""

    dim = 8
    seen: list = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 的约定命名
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).seen.append({
            "path": self.path,
            "body": body,
            "auth": self.headers.get("Authorization"),
        })

        inputs = body.get("input") or []
        if isinstance(inputs, str):
            inputs = [inputs]

        payload = json.dumps({
            "data": [
                {"embedding": [0.1] * type(self).dim, "index": index,
                 "object": "embedding"}
                for index, _ in enumerate(inputs)
            ],
            "model": body.get("model"),
            "object": "list",
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 静音，避免污染测试输出
        return


def test_api_backend_real_http_round_trip():
    """用真实 HTTP 服务（不是 mock）验证一次完整往返。

    覆盖 mock 测不到的东西：httpx 实际发出去的请求长什么样、JSON 怎么编码、
    响应怎么解析——这几处一旦和接口约定不一致，只有真发一次才看得出来。
    """
    _FakeEmbeddingHandler.dim = 16
    _FakeEmbeddingHandler.seen = []
    server = HTTPServer(("127.0.0.1", 0), _FakeEmbeddingHandler)  # 端口 0 = 随便给个空闲端口
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = OpenAICompatEmbedding(
            model="text-embedding-v3",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-test", dim=0)

        assert asyncio.run(backend.ensure_dim()) == 16

        vectors = asyncio.run(backend.embed(["退款多久到账", "怎么开发票"]))
        assert [len(vector) for vector in vectors] == [16, 16]

        # seen[0] 是 ensure_dim 的探测请求，seen[-1] 才是刚才那次批量请求
        probe = _FakeEmbeddingHandler.seen[0]
        request = _FakeEmbeddingHandler.seen[-1]
        assert probe["body"]["input"] == ["维度探测"]
        assert request["path"] == "/v1/embeddings"
        assert request["body"]["model"] == "text-embedding-v3"
        assert request["body"]["encoding_format"] == "float"
        assert request["body"]["input"] == ["退款多久到账", "怎么开发票"]
        assert request["auth"] == "Bearer sk-test"
    finally:
        server.shutdown()
        server.server_close()


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
