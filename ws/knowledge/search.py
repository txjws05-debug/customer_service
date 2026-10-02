"""命令行检索自测：不启动整个服务，直接看知识库检索命中了什么。

用法：
    python -m ws.knowledge.search "退款多久到账"
    python -m ws.knowledge.search "那要多久" --kinds faq
    python -m ws.knowledge.search "物流不更新" -k 5

输出每条命中的总分、向量分、关键词分，方便调 KNOWLEDGE_MIN_SCORE。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from ws.knowledge import store
from ws.knowledge.embedding import get_embedding_backend
from ws.utils import database

DEFAULT_KINDS = ("faq", "policy")


async def run(query: str, kinds: list[str], top_k: int) -> None:
    database.init_db_engine()
    try:
        backend = get_embedding_backend()
        query_vector = (await backend.embed([query]))[0]
        hits = await store.search(
            query_vector=query_vector, query_text=query, kinds=kinds, top_k=top_k)

        print(f"查询：{query}")
        print(f"embedding：{backend.name}（dim={backend.dim}）")
        print(f"范围：{', '.join(kinds)}    知识条数：{await store.count_chunks()}")
        print("-" * 72)
        if not hits:
            print("没有任何候选（知识库可能是空的，先跑 python -m ws.knowledge.reindex）")
            return
        for rank, hit in enumerate(hits, start=1):
            print(f"{rank}. 总分={hit.score:.3f}  向量={hit.vector_score:.3f}  "
                  f"关键词={hit.keyword_score:.3f}  [{hit.kind}] {hit.doc_id}")
            print(f"   {hit.title}")
            print(f"   {hit.content[:60]}...")
    finally:
        await database.close_db_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库检索自测")
    parser.add_argument("query", help="要检索的问题")
    parser.add_argument("--kinds", default=",".join(DEFAULT_KINDS),
                        help="检索范围，逗号分隔（faq,policy）")
    parser.add_argument("-k", "--top-k", type=int, default=4, help="返回条数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    kinds = [item.strip() for item in args.kinds.split(",") if item.strip()]
    asyncio.run(run(args.query, kinds, args.top_k))


if __name__ == "__main__":
    main()
