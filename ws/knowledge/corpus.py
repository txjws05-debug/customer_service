"""知识语料：加载与校验。

语料以 JSON 形式放在仓库里（会随 api 镜像一起发布），启动时按内容哈希判断
是否需要重建向量索引——改了语料只要重启容器，索引会自动跟上。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ws.knowledge.corpus")

DATA_FILE = Path(__file__).parent / "data" / "knowledge.json"

# kind 取值：faq 是短问答，policy 是规则条款长文。
# FAQProvider 只查 faq，RAGProvider 查 policy，两者检索范围不同。
KIND_FAQ = "faq"
KIND_POLICY = "policy"

_REQUIRED_FIELDS = ("doc_id", "kind", "title", "content")


@dataclass(frozen=True)
class KnowledgeDoc:
    doc_id: str
    kind: str
    title: str
    content: str
    source: str = ""
    # 口语化别名词（空格分隔）。用户很少照着文档标题提问，
    # 例如「钱什么时候退回来」对应的是「退款多久到账？」——
    # 别名参与向量化，是提升召回最直接的手段（RAG 里的查询/文档扩展）。
    aliases: str = ""

    @property
    def embedding_text(self) -> str:
        """参与向量化的文本。

        标题重复两次是给标题加权——用户提问往往更像标题而不是正文。
        """
        parts = [self.title, self.title, self.content]
        if self.aliases:
            parts.append(self.aliases)
        return "\n".join(parts)


def load_corpus(path: Path = DATA_FILE) -> list[KnowledgeDoc]:
    """读取并校验语料；格式错误直接抛错，避免把坏数据灌进库里。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} 顶层必须是数组")

    docs: list[KnowledgeDoc] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path.name} 第 {index + 1} 条不是对象")
        for field in _REQUIRED_FIELDS:
            if not str(item.get(field, "")).strip():
                raise ValueError(f"{path.name} 第 {index + 1} 条缺少字段 {field}")

        doc_id = str(item["doc_id"]).strip()
        if doc_id in seen:
            raise ValueError(f"{path.name} 存在重复的 doc_id：{doc_id}")
        seen.add(doc_id)

        docs.append(KnowledgeDoc(
            doc_id=doc_id,
            kind=str(item["kind"]).strip(),
            title=str(item["title"]).strip(),
            content=str(item["content"]).strip(),
            source=str(item.get("source", "")).strip(),
            aliases=str(item.get("aliases", "")).strip(),
        ))

    return docs


def corpus_hash(docs: list[KnowledgeDoc]) -> str:
    """语料内容指纹：变了就说明该重建索引。"""
    payload = json.dumps(
        [
            {
                "doc_id": doc.doc_id,
                "kind": doc.kind,
                "title": doc.title,
                "content": doc.content,
                "source": doc.source,
                "aliases": doc.aliases,
            }
            for doc in docs
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
