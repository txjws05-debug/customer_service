"""知识库的 pgvector 存储与检索。

设计要点：
- **不引入新依赖**：直接用原生 SQL 操作 vector 列（向量以 '[0.1,0.2,...]'
  字符串传入再 CAST 成 vector），因此不需要 pgvector 的 Python 包，
  uv.lock 也不用动。
- **混合检索**：先用 HNSW 索引按余弦距离召回一批候选，再把「向量相似度」和
  pg_trgm 的「字面相似度」加权排序。中文短问句上，两者互补效果明显好于纯向量。
- **自愈式建表**：维度对不上（换了 embedding 模型）时自动重建表和索引。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from ws.config.config import settings
from ws.utils import database

logger = logging.getLogger("ws.knowledge.store")

# 混合检索权重：向量为主、字面为辅
_VECTOR_WEIGHT = 0.7
_KEYWORD_WEIGHT = 0.3

_pg_trgm_ready: bool | None = None


@dataclass
class KnowledgeRow:
    """待写入知识库的一条记录。"""

    doc_id: str
    kind: str
    title: str
    content: str
    source: str
    embedding: list[float]


@dataclass
class SearchHit:
    """一条检索结果。"""

    doc_id: str
    kind: str
    title: str
    content: str
    source: str
    score: float
    vector_score: float
    keyword_score: float

    def render(self) -> str:
        """给 LLM 看的文本：带上标题和来源，便于它引用出处。"""
        head = f"【{self.title}】"
        if self.source:
            head += f"（来源：{self.source}）"
        return f"{head}\n{self.content}"


def vector_literal(vector: list[float]) -> str:
    """pgvector 接受的字符串形式：'[0.1,0.2,0.3]'。"""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


async def _has_pg_trgm(session) -> bool:
    """pg_trgm 是否可用。不可用时退化为纯向量检索，而不是直接报错。"""
    global _pg_trgm_ready
    if _pg_trgm_ready is None:
        result = await session.execute(text(
            "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
        _pg_trgm_ready = result.scalar_one_or_none() is not None
        if not _pg_trgm_ready:
            logger.warning("pg_trgm 扩展不可用，关键词加权已跳过（仅用向量检索）")
    return _pg_trgm_ready


async def ensure_schema(dim: int) -> None:
    """建扩展/建表/建索引；维度变化时重建。启动时调用，幂等。"""
    async with database.session_factory() as session:
        # vector 扩展本该由 deploy/postgres/init/01-extensions.sql 建好；
        # 这里兜底检查，缺了就给一条能直接照做的提示。
        result = await session.execute(text(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        if result.scalar_one_or_none() is None:
            try:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - 需要把原因讲清楚
                raise RuntimeError(
                    "数据库缺少 vector 扩展，且当前用户无权创建。"
                    "请用超级用户执行：CREATE EXTENSION vector;"
                    f"（原始错误：{exc}）") from exc

        # 已有表的向量维度
        result = await session.execute(text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = to_regclass('knowledge_chunks') "
            "AND attname = 'embedding'"))
        existing_dim = result.scalar_one_or_none()
        if existing_dim is not None and existing_dim != dim:
            logger.warning(
                "embedding 维度从 %s 变为 %s，重建知识表与索引", existing_dim, dim)
            await session.execute(text("DROP TABLE IF EXISTS knowledge_chunks"))

        await session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id         BIGSERIAL PRIMARY KEY,
                doc_id     TEXT NOT NULL,
                kind       TEXT NOT NULL,
                title      TEXT NOT NULL,
                content    TEXT NOT NULL,
                source     TEXT NOT NULL DEFAULT '',
                embedding  vector({dim}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_knowledge_chunks_doc
                ON knowledge_chunks (doc_id)
        """))
        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_kind
                ON knowledge_chunks (kind)
        """))
        # 余弦距离的 HNSW 索引：候选召回那一层靠它
        await session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
                ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
        """))
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS knowledge_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """))
        await session.commit()


async def load_meta() -> dict[str, str]:
    async with database.session_factory() as session:
        result = await session.execute(text("SELECT key, value FROM knowledge_meta"))
        return {row[0]: row[1] for row in result.all()}


async def save_meta(items: dict[str, str]) -> None:
    if not items:
        return
    async with database.session_factory() as session:
        for key, value in items.items():
            await session.execute(text("""
                INSERT INTO knowledge_meta (key, value) VALUES (:key, :value)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """), {"key": key, "value": value})
        await session.commit()


async def count_chunks() -> int:
    async with database.session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM knowledge_chunks"))
        return int(result.scalar_one())


async def replace_all(rows: list[KnowledgeRow]) -> None:
    """整表替换：知识库是从文件重建的派生数据，全量重写最简单也最不容易出错。"""
    async with database.session_factory() as session:
        await session.execute(text("TRUNCATE knowledge_chunks RESTART IDENTITY"))
        if rows:
            await session.execute(
                text("""
                    INSERT INTO knowledge_chunks
                        (doc_id, kind, title, content, source, embedding)
                    VALUES
                        (:doc_id, :kind, :title, :content, :source,
                         CAST(:embedding AS vector))
                """),
                [
                    {
                        "doc_id": row.doc_id,
                        "kind": row.kind,
                        "title": row.title,
                        "content": row.content,
                        "source": row.source,
                        "embedding": vector_literal(row.embedding),
                    }
                    for row in rows
                ],
            )
        await session.commit()


async def search(query_vector: list[float],
                 query_text: str,
                 kinds: list[str],
                 top_k: int | None = None,
                 candidates: int | None = None) -> list[SearchHit]:
    """混合检索：HNSW 召回候选 → 向量分 + 字面分加权排序。"""
    top_k = top_k or settings.knowledge_top_k
    candidates = candidates or max(settings.knowledge_candidates, top_k)

    async with database.session_factory() as session:
        use_trgm = await _has_pg_trgm(session)
        keyword_expr = (
            "similarity(title || ' ' || content, :query_text)" if use_trgm else "0.0")
        sql = f"""
            WITH candidates AS (
                SELECT id, doc_id, kind, title, content, source,
                       embedding <=> CAST(:query_vector AS vector) AS distance
                FROM knowledge_chunks
                WHERE kind = ANY(CAST(:kinds AS text[]))
                ORDER BY distance
                LIMIT :candidate_limit
            )
            SELECT doc_id, kind, title, content, source,
                   distance,
                   1 - distance AS vector_score,
                   {keyword_expr} AS keyword_score,
                   :vector_weight * (1 - distance)
                     + :keyword_weight * {keyword_expr} AS score
            FROM candidates
            ORDER BY score DESC
            LIMIT :top_k
        """
        result = await session.execute(text(sql), {
            "query_vector": vector_literal(query_vector),
            "query_text": query_text,
            "kinds": kinds,
            "candidate_limit": candidates,
            "top_k": top_k,
            "vector_weight": _VECTOR_WEIGHT,
            "keyword_weight": _KEYWORD_WEIGHT if use_trgm else 0.0,
        })
        rows = result.mappings().all()

    return [
        SearchHit(
            doc_id=row["doc_id"],
            kind=row["kind"],
            title=row["title"],
            content=row["content"],
            source=row["source"],
            score=float(row["score"]),
            vector_score=float(row["vector_score"]),
            keyword_score=float(row["keyword_score"]),
        )
        for row in rows
    ]
