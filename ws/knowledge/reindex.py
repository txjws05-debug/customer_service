"""知识库索引：把语料向量化后写入 pgvector。

什么时候会重建：
- 语料内容变了（内容哈希对不上）
- 换了 embedding 模型 / 维度变了
- 表是空的（首次启动）
- 显式 `--force`

命令行用法：
    python -m ws.knowledge.reindex            # 需要时才重建
    python -m ws.knowledge.reindex --force    # 强制重建
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from ws.config.config import settings
from ws.knowledge import store
from ws.knowledge.corpus import corpus_hash, load_corpus
from ws.knowledge.embedding import get_embedding_backend
from ws.utils import database

logger = logging.getLogger("ws.knowledge.reindex")

# 单次请求的条数上限，避免一次性把语料全塞给 embedding 接口
_BATCH_SIZE = 16

META_MODEL = "embedding_model"
META_DIM = "embedding_dim"
META_CORPUS = "corpus_hash"
META_COUNT = "chunk_count"


@dataclass
class IndexResult:
    reindexed: bool
    chunks: int
    embedding_backend: str
    reason: str = ""


async def ensure_index(force: bool = False) -> IndexResult:
    """幂等地保证索引与语料、模型一致。"""
    backend = get_embedding_backend()
    docs = load_corpus()
    digest = corpus_hash(docs)

    # 维度变化会在这里自动重建表
    await store.ensure_schema(backend.dim)

    meta = await store.load_meta()
    stored_count = await store.count_chunks()

    if force:
        reason = "手动指定 --force"
    elif meta.get(META_MODEL) != backend.name:
        reason = f"embedding 模型变化（{meta.get(META_MODEL)} -> {backend.name}）"
    elif meta.get(META_DIM) != str(backend.dim):
        reason = f"向量维度变化（{meta.get(META_DIM)} -> {backend.dim}）"
    elif meta.get(META_CORPUS) != digest:
        reason = "语料内容变化"
    elif stored_count != len(docs):
        reason = f"条数不一致（库内 {stored_count}，语料 {len(docs)}）"
    else:
        logger.info("知识索引已是最新：%d 条，embedding=%s", stored_count, backend.name)
        return IndexResult(False, stored_count, backend.name, "已是最新")

    logger.info("重建知识索引：%s（%d 条）", reason, len(docs))

    rows: list[store.KnowledgeRow] = []
    for start in range(0, len(docs), _BATCH_SIZE):
        batch = docs[start:start + _BATCH_SIZE]
        vectors = await backend.embed([doc.embedding_text for doc in batch])
        rows.extend(
            store.KnowledgeRow(
                doc_id=doc.doc_id,
                kind=doc.kind,
                title=doc.title,
                content=doc.content,
                source=doc.source,
                embedding=vector,
            )
            for doc, vector in zip(batch, vectors)
        )

    await store.replace_all(rows)
    await store.save_meta({
        META_MODEL: backend.name,
        META_DIM: str(backend.dim),
        META_CORPUS: digest,
        META_COUNT: str(len(rows)),
    })
    logger.info("知识索引重建完成：%d 条，embedding=%s", len(rows), backend.name)
    return IndexResult(True, len(rows), backend.name, reason)


async def _main(force: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    database.init_db_engine()
    try:
        result = await ensure_index(force=force)
        print(f"重建索引: {'是' if result.reindexed else '否'}（{result.reason}）")
        print(f"知识条数: {result.chunks}")
        print(f"embedding 后端: {result.embedding_backend}")
        print(f"维度: {settings.embedding_dim}")
    finally:
        await database.close_db_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="重建知识库向量索引")
    parser.add_argument("--force", action="store_true", help="强制重建，忽略哈希比对")
    args = parser.parse_args()
    asyncio.run(_main(force=args.force))


if __name__ == "__main__":
    main()
