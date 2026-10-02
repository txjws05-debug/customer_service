"""文本向量化：RAG 检索的 embedding 层。

两种后端，按配置自动选择：

1) API 后端（推荐）：配了 EMBEDDING_BASE_URL + EMBEDDING_MODEL 后，调用
   OpenAI 兼容的 /embeddings 接口。硅基流动、阿里云百炼、OpenAI 等都提供
   兼容接口，换个 base_url 就能用，不需要改代码。
2) 本地后端（默认兜底）：不依赖任何外部服务，把文本切成「字符 n-gram + 拉丁词」
   特征，再用带符号哈希投影到固定维度（Hashing Trick）。它是**词法向量**，
   靠字面重合度工作；好处是零依赖、离线可用、结果稳定，没配模型时也能先把
   整条 RAG 链路跑起来。

约定：所有后端产出的向量都做 L2 归一化，这样 pgvector 的余弦距离 `<=>`
与向量夹角等价，检索可以直接按它排序。
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
from abc import ABC, abstractmethod

import httpx

from ws.config.config import settings

logger = logging.getLogger("ws.knowledge.embedding")

# 中日韩统一表意文字（含扩展 A 区）
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_LATIN_PATTERN = re.compile(r"[a-z0-9]+")

# 二元词比单字更能区分中文语义；拉丁词按整词算
_WEIGHT_UNIGRAM = 1.0
_WEIGHT_BIGRAM = 1.6
_WEIGHT_WORD = 1.6


def extract_features(text: str) -> list[tuple[str, float]]:
    """把文本切成 (特征, 权重)。

    建索引和查询必须走同一个函数，否则两侧特征空间不一致，检索结果会失真。
    """
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    features: list[tuple[str, float]] = []

    for word in _LATIN_PATTERN.findall(normalized):
        features.append((word, _WEIGHT_WORD))

    for run in _CJK_PATTERN.findall(normalized):
        for char in run:
            features.append((char, _WEIGHT_UNIGRAM))
        for left, right in zip(run, run[1:]):
            features.append((left + right, _WEIGHT_BIGRAM))

    return features


def _project(feature: str, dim: int) -> tuple[int, float]:
    """把特征哈希到 [0, dim) 并给出随机符号。

    带符号是为了让不同特征碰撞到同一维时互相抵消而不是一味累加，
    减少哈希冲突带来的相似度虚高。
    """
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, (1.0 if value >> 63 else -1.0)


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return list(vector)
    return [value / norm for value in vector]


class EmbeddingBackend(ABC):
    """embedding 后端接口。"""

    name: str = ""
    #: 向量维度。0 表示「还没确定」——API 后端在第一次调用时自动探测。
    dim: int = 0

    async def ensure_dim(self) -> int:
        """返回确定后的维度。

        本地后端构造时维度就已知；API 后端需要先探一次才知道模型输出多少维
        （百炼 text-embedding-v4 有 8 种可选维度），所以建表前必须调它。
        """
        return self.dim

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """把一批文本转成向量（已 L2 归一化）。"""
        raise NotImplementedError


class HashingEmbedding(EmbeddingBackend):
    """本地词法向量：字符 n-gram + 带符号哈希投影，不需要任何外部服务。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"local-hashing-{dim}"

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature, weight in extract_features(text):
            index, sign = _project(feature, self.dim)
            vector[index] += sign * weight
        return l2_normalize(vector)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # 纯 CPU 计算，微秒级，不需要丢线程池
        return [self.embed_text(text) for text in texts]


def _reject_non_ascii(name: str, value: str) -> None:
    """HTTP 请求头和 URL 只能是 ASCII。

    否则 httpx 会抛一个完全看不出原因的 `UnicodeEncodeError: 'ascii' codec
    can't encode characters in position N`——线上真实踩过：把文档里的中文
    占位符原样填进了 EMBEDDING_API_KEY。这里提前给出能直接照做的报错。
    """
    if not value or value.isascii():
        return

    position = next(i for i, char in enumerate(value) if not char.isascii())
    raise ValueError(
        f"{name} 里出现了非 ASCII 字符（第 {position} 位起）。"
        f"HTTP 请求头和 URL 只能是 ASCII，最常见的原因是把配置文档里的"
        f"占位符原样填了进去。请改成真实值：百炼的 EMBEDDING_BASE_URL 是 "
        f"https://dashscope.aliyuncs.com/compatible-mode/v1，"
        f"EMBEDDING_API_KEY 形如 sk- 开头、后面全是字母数字。"
        f"当前值的长度是 {len(value)}。")


class OpenAICompatEmbedding(EmbeddingBackend):
    """调用 OpenAI 兼容的 /embeddings 接口。

    已按阿里云百炼（text-embedding-v3/v4）、硅基流动、OpenAI 的公共约定实现：
      POST {base_url}/embeddings
      {"model": "...", "input": ["文本1", "文本2"]}
      -> {"data": [{"embedding": [...], "index": 0}, ...]}
    """

    def __init__(self, model: str, base_url: str, api_key: str | None,
                 dim: int = 0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.dim = dim
        self.name = f"{model}@{self.base_url}"

        # 配置错误要在构造时就暴露，别等到发请求才炸一个看不懂的编码错误
        _reject_non_ascii("EMBEDDING_BASE_URL", self.base_url)
        _reject_non_ascii("EMBEDDING_MODEL", self.model)
        _reject_non_ascii("EMBEDDING_API_KEY", self.api_key)

    async def _request(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        return [item["embedding"] for item in body["data"]]

    async def ensure_dim(self) -> int:
        if self.dim <= 0:
            vectors = await self._request(["维度探测"])
            self.dim = len(vectors[0])
            logger.info("探测到 embedding 模型 %s 的输出维度 = %d",
                        self.model, self.dim)
        return self.dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await self._request(texts)
        if not vectors:
            return []

        for vector in vectors:
            # 维度对不上就写不进 vector(N) 列，这里提前给出可操作的报错
            if self.dim and len(vector) != self.dim:
                raise ValueError(
                    f"embedding 维度不一致：模型 {self.model} 返回 {len(vector)} 维，"
                    f"而 EMBEDDING_DIM 配的是 {self.dim} 维。"
                    f"把 EMBEDDING_DIM 改成 {len(vector)}（或留空让它自动探测）后重启，"
                    f"启动时会自动重建索引。")

        self.dim = self.dim or len(vectors[0])
        return [l2_normalize(vector) for vector in vectors]


_backend: EmbeddingBackend | None = None


def build_embedding_backend() -> EmbeddingBackend:
    """按配置构造后端；没配 API 就退回本地词法向量。"""
    if settings.embedding_base_url and settings.embedding_model:
        if not settings.embedding_api_key:
            # 只删掉 key 而留着 base_url/model 是最容易踩的组合：
            # 代码仍会选用 API 后端，然后拿着空 key 去请求，检索全部失败。
            logger.warning(
                "配置了 EMBEDDING_BASE_URL/MODEL 但 EMBEDDING_API_KEY 为空："
                "如果该服务需要鉴权，调用会返回 401、知识检索将不可用。"
                "想退回本地词法向量请把 BASE_URL/MODEL/API_KEY 三项一起清掉；"
                "本地无鉴权服务（如自建 TEI/Ollama）可忽略此提示。")
        return OpenAICompatEmbedding(
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            # 0 = 首次调用时自动探测（不填 EMBEDDING_DIM 就走这条路）
            dim=settings.embedding_dim or 0,
        )
    # 本地后端必须有确定维度，默认 512
    return HashingEmbedding(dim=settings.embedding_dim or 512)


def get_embedding_backend() -> EmbeddingBackend:
    """进程内复用同一个后端实例。"""
    global _backend
    if _backend is None:
        _backend = build_embedding_backend()
        logger.info("embedding 后端=%s dim=%s", _backend.name,
                    _backend.dim or "待探测")
    return _backend


def reset_embedding_backend() -> None:
    """测试用：清掉缓存，下次重新按配置构造。"""
    global _backend
    _backend = None
