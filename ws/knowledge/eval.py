"""RAG 检索质量评测：Recall@k / MRR / 超纲拒答率 + badcase 清单。

为什么要有它：改检索（换向量模型、调权重、加别名、调 min_score）如果只靠"感觉好像准了"，
就永远说不清"改之前多少、改之后多少"。这个模块把评测集跑成一张表，
让每一次调整都有前后对比，也顺手产出 badcase 清单。

两种后端，覆盖两种场景：

- `--backend memory`：纯 Python 内存余弦 + 字符 bigram 哈希向量（deterministic）。
  不需要数据库、不需要外部 API，CI 与本地都能跑 —— 用来验证"评测本身是对的"，
  以及在没有 embedding key 的机器上做粗筛。
- `--backend db`：走真实 pgvector + 配置里的 embedding 后端（百炼）。
  **真实质量数字必须用这个跑**（部署脚本会在自检里跑一次，数字进 CI 日志）。

用法：
    python -m ws.knowledge.eval                      # 内存后端
    python -m ws.knowledge.eval --backend db --sweep  # 真实检索 + 多配置对比
    python -m ws.knowledge.eval --backend db --json eval.json --markdown eval.md

指标口径（都先过 `KNOWLEDGE_MIN_SCORE` 门槛，与线上一致）：
- Recall@k：有标准答案的问题里，正确答案出现在前 k 条的比例；
- MRR：第一个正确答案排名的倒数均值（排第 1 得 1.0，第 3 得 0.33，没命中得 0）；
- 超纲拒答率：expected 为空的问题里，被门槛挡掉（不硬扯一条）的比例。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from ws.config.config import settings

DATA_DIR = Path(__file__).resolve().parent / "data"
EVAL_FILE = DATA_DIR / "rag_eval.json"

DEFAULT_KS = (1, 3, 5)
#: 评测时多取一些候选，badcase 里就能看到"正确答案到底排第几"
RETRIEVE_N = 10

#: 检索配置的对比组：--sweep 会各跑一遍，输出对比表
SWEEP_CONFIGS: list[tuple[str, dict]] = [
    ("向量-only", {"vector_weight": 1.0, "keyword_weight": 0.0,
                   "keyword_mode": "none", "include_aliases": True}),
    ("混合 0.7/0.3（similarity）",
     {"vector_weight": 0.7, "keyword_weight": 0.3, "keyword_mode": "similarity",
      "include_aliases": True}),
    ("混合（字面分不含别名）",
     {"vector_weight": 0.7, "keyword_weight": 0.3, "keyword_mode": "similarity",
      "include_aliases": False}),
    ("混合 0.7/0.3（word_similarity）",
     {"vector_weight": 0.7, "keyword_weight": 0.3, "keyword_mode": "word_similarity",
      "include_aliases": True}),
]


# ============================================================ 评测集
@dataclass(frozen=True)
class EvalCase:
    query: str
    expected: tuple[str, ...]
    category: str = "direct"


@dataclass
class Hit:
    doc_id: str
    title: str
    score: float


@dataclass
class Outcome:
    case: EvalCase
    hits: list[Hit]          # 已过门槛、按分数降序
    raw_hits: list[Hit]      # 未过门槛的候选（用于解释为什么被拒）

    @property
    def first_rank(self) -> int:
        """第一个正确命中的排名（1 起）；没命中返回 0。"""
        if not self.case.expected:
            return 0
        for index, hit in enumerate(self.hits, start=1):
            if hit.doc_id in self.case.expected:
                return index
        return 0

    @property
    def refused(self) -> bool:
        return not self.hits


def load_eval_set(path: Path = EVAL_FILE) -> list[EvalCase]:
    """读取评测集并校验：expected 里的 doc_id 必须在语料里真实存在。

    写错 id 的评测集比没有评测集更糟 —— 它会让人以为检索坏了。
    """
    from ws.knowledge.corpus import load_corpus

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload["cases"] if isinstance(payload, dict) else payload
    known = {doc.doc_id for doc in load_corpus()}

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_cases):
        query = str(item["query"]).strip()
        if not query:
            raise ValueError(f"{path.name} 第 {index + 1} 条 query 为空")
        if query in seen:
            raise ValueError(f"{path.name} 存在重复问题：{query}")
        seen.add(query)

        expected = tuple(str(x).strip() for x in item.get("expected", []))
        unknown = [doc_id for doc_id in expected if doc_id not in known]
        if unknown:
            raise ValueError(
                f"{path.name} 第 {index + 1} 条的 expected 不在语料里：{unknown}")
        cases.append(EvalCase(
            query=query, expected=expected,
            category=str(item.get("category", "direct"))))

    if not cases:
        raise ValueError(f"{path.name} 没有任何用例")
    return cases


# ============================================================ 离线向量
def _trigrams(text: str) -> set[str]:
    """近似 pg_trgm：两侧补空格后切 3 元组。"""
    normalized = "  " + re.sub(r"\s+", " ", text.strip().lower()) + " "
    return {normalized[i:i + 3] for i in range(len(normalized) - 2)}


def trigram_similarity(left: str, right: str) -> float:
    """对应 pg_trgm 的 similarity()：交集 / 并集。"""
    a, b = _trigrams(left), _trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def trigram_word_similarity(query: str, text: str) -> float:
    """近似 pg_trgm 的 word_similarity()：查询侧的覆盖率。

    短问题 vs 长文档时，`similarity()` 会被长文档的 trigram 稀释得几乎为 0，
    而 word_similarity 看的是"问题里的词在文档中出现多少"，更适合知识库场景。
    """
    a, b = _trigrams(query), _trigrams(text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


class HashingEmbedding:
    """字符 bigram 哈希向量：deterministic、零依赖，仅用于离线评测。

    用 zlib.crc32 而不是内置 hash() —— 后者受 PYTHONHASHSEED 影响，
    换个进程结果就变，评测就不可复现了。
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    async def ensure_dim(self) -> int:
        return self.dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        import math

        vector = [0.0] * self.dim
        normalized = re.sub(r"\s+", "", text.lower())
        grams = [normalized[i:i + 2] for i in range(max(len(normalized) - 1, 1))]
        grams += list(normalized)  # 超短 query 也保证有信号
        for gram in grams:
            vector[zlib.crc32(gram.encode("utf-8")) % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


# ============================================================ 检索器
class MemoryRetriever:
    """内存检索：与线上同一套打分公式（向量分 + 字面分加权）。"""

    def __init__(self, docs, embedding, *, vector_weight: float, keyword_weight: float,
                 keyword_mode: str, include_aliases: bool = True):
        self.docs = docs
        self.embedding = embedding
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.keyword_mode = keyword_mode
        self.include_aliases = include_aliases
        self.vectors: list[list[float]] = []

    async def prepare(self) -> None:
        self.vectors = await self.embedding.embed([doc.embedding_text for doc in self.docs])

    def _lexical(self, query: str, doc) -> float:
        if self.keyword_mode == "none" or self.keyword_weight <= 0:
            return 0.0
        # 与 SQL 侧保持同样的口径：别名参不参与字面分是本次对比的一个维度
        text = f"{doc.title} {doc.content}"
        if self.include_aliases:
            text = f"{doc.title} {doc.aliases} {doc.content}"
        if self.keyword_mode == "word_similarity":
            return trigram_word_similarity(query, text)
        return trigram_similarity(query, text)

    async def __call__(self, query: str, limit: int) -> list[Hit]:
        query_vector = (await self.embedding.embed([query]))[0]
        scored: list[tuple[float, object]] = []
        for doc, vector in zip(self.docs, self.vectors):
            score = (self.vector_weight * _cosine(query_vector, vector)
                     + self.keyword_weight * self._lexical(query, doc))
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [Hit(doc_id=doc.doc_id, title=doc.title, score=score)
                for score, doc in scored[:limit]]


def make_db_retriever(*, kinds: list[str], embedding, vector_weight: float,
                      keyword_weight: float, keyword_mode: str,
                      include_aliases: bool = True):
    """真实检索：pgvector + 配置里的 embedding 后端（与线上同一条路径）。"""
    from ws.knowledge import store

    async def retrieve(query: str, limit: int) -> list[Hit]:
        query_vector = (await embedding.embed([query]))[0]
        hits = await store.search(
            query_vector=query_vector, query_text=query, kinds=kinds,
            top_k=limit, candidates=max(settings.knowledge_candidates, limit),
            vector_weight=vector_weight, keyword_weight=keyword_weight,
            keyword_mode=keyword_mode, include_aliases=include_aliases)
        return [Hit(doc_id=hit.doc_id, title=hit.title, score=hit.score) for hit in hits]

    return retrieve


# ============================================================ 评测
Retriever = Callable[[str, int], Awaitable[list[Hit]]]


async def collect(cases: list[EvalCase], retrieve: Retriever, *,
                  top_n: int = RETRIEVE_N) -> list[Outcome]:
    """只取候选、不套门槛：这样一次检索就能在多个 min_score 下比较。"""
    outcomes: list[Outcome] = []
    for case in cases:
        raw = await retrieve(case.query, top_n)
        outcomes.append(Outcome(case=case, hits=list(raw), raw_hits=list(raw)))
    return outcomes


def summarize(outcomes: list[Outcome], *, min_score: float,
              ks: tuple[int, ...] = DEFAULT_KS) -> dict:
    """按 min_score 门槛结算指标（与线上判定完全一致）。"""
    gated = [
        Outcome(case=o.case,
                hits=[hit for hit in o.raw_hits if hit.score >= min_score],
                raw_hits=o.raw_hits)
        for o in outcomes
    ]
    answered = [o for o in gated if o.case.expected]
    out_of_scope = [o for o in gated if not o.case.expected]

    recall = {
        k: (sum(1 for o in answered if 0 < o.first_rank <= k) / len(answered))
        if answered else 0.0
        for k in ks
    }
    reciprocal = [(1.0 / o.first_rank) if o.first_rank else 0.0 for o in answered]

    by_category: dict[str, dict] = {}
    for category in sorted({o.case.category for o in gated}):
        group = [o for o in gated if o.case.category == category]
        group_answered = [o for o in group if o.case.expected]
        by_category[category] = {
            "count": len(group),
            f"recall@{max(ks)}": (
                sum(1 for o in group_answered if 0 < o.first_rank <= max(ks))
                / len(group_answered)) if group_answered else None,
            "refused": sum(1 for o in group if o.refused),
        }

    misses = [o for o in answered if not (0 < o.first_rank <= max(ks))]
    leaks = [o for o in out_of_scope if not o.refused]
    refusal = (len(out_of_scope) - len(leaks)) / len(out_of_scope) if out_of_scope else None

    return {
        "count": len(outcomes),
        "min_score": min_score,
        "recall": {f"recall@{k}": round(value, 4) for k, value in recall.items()},
        "mrr": round(statistics.fmean(reciprocal), 4) if reciprocal else 0.0,
        "refusal_rate": round(refusal, 4) if refusal is not None else None,
        # 正例召回与负例拒答的平衡（Youden 思路）：调门槛时用它挑最优点
        "balanced": round(
            (recall[max(ks)] + (refusal or 0.0)) / 2, 4),
        "by_category": by_category,
        "misses": misses,
        "leaks": leaks,
        "outcomes": gated,
    }


async def evaluate(cases: list[EvalCase], retrieve: Retriever, *,
                   ks: tuple[int, ...] = DEFAULT_KS, min_score: float,
                   top_n: int = RETRIEVE_N) -> dict:
    """跑一遍评测：先按 top_n 取候选，再套 min_score 门槛（与线上判定一致）。"""
    return summarize(await collect(cases, retrieve, top_n=top_n),
                     min_score=min_score, ks=ks)


def score_distribution(outcomes: list[Outcome]) -> dict:
    """正例 / 负例的 top1 分数分布 —— 门槛该定在哪，看这个而不是拍脑袋。"""
    def top1(group):
        scores = [o.raw_hits[0].score for o in group if o.raw_hits]
        if not scores:
            return None
        return {
            "min": round(min(scores), 4),
            "p50": round(statistics.median(scores), 4),
            "max": round(max(scores), 4),
        }

    positive = [o for o in outcomes if o.case.expected]
    negative = [o for o in outcomes if not o.case.expected]
    return {"in_scope": top1(positive), "out_of_scope": top1(negative)}


def threshold_sweep(outcomes: list[Outcome], *,
                    ks: tuple[int, ...] = DEFAULT_KS) -> list[dict]:
    """在一组候选门槛上结算指标，找出召回与拒答的平衡点。

    候选门槛来自真实分数：正例 top1 的最低分 ~ 负例 top1 的最高分之间取若干点，
    比"每隔 0.1 试一次"更有针对性。
    """
    positive_top1 = [o.raw_hits[0].score for o in outcomes
                     if o.case.expected and o.raw_hits]
    negative_top1 = [o.raw_hits[0].score for o in outcomes
                     if not o.case.expected and o.raw_hits]
    if not positive_top1:
        return []

    low = min(negative_top1) if negative_top1 else min(positive_top1)
    high = max(positive_top1)
    if high <= low:
        candidates = [round(low, 4)]
    else:
        candidates = sorted({
            round(low + (high - low) * index / 5, 4) for index in range(6)
        } | {round(statistics.median(positive_top1), 4)})

    sweep = []
    for threshold in candidates:
        summary = summarize(outcomes, min_score=threshold, ks=ks)
        sweep.append({
            "min_score": threshold,
            f"recall@{max(ks)}": summary["recall"][f"recall@{max(ks)}"],
            "refusal_rate": summary["refusal_rate"],
            "balanced": summary["balanced"],
        })
    return sweep


# ============================================================ 报告
def render_markdown(result: dict, *, label: str, badcase_limit: int = 8) -> str:
    lines = [f"### {label}", ""]
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    for key, value in result["recall"].items():
        lines.append(f"| {key} | {value * 100:.1f}% |")
    lines.append(f"| MRR | {result['mrr']:.3f} |")
    if result["refusal_rate"] is not None:
        lines.append(f"| 超纲拒答率 | {result['refusal_rate'] * 100:.1f}% |")
    lines.append(f"| min_score 门槛 | {result['min_score']} |")
    lines.append("")

    lines.append("| 分类 | 用例数 | Recall@5 | 被拒答 |")
    lines.append("| --- | --- | --- | --- |")
    for category, stats in result["by_category"].items():
        recall = stats["recall@5"]
        shown = "—" if recall is None else f"{recall * 100:.0f}%"
        lines.append(
            f"| {category} | {stats['count']} | {shown} | {stats['refused']} |")
    lines.append("")

    misses = result["misses"][:badcase_limit]
    if misses:
        lines.append(f"**badcase（正确答案没进前 {max(DEFAULT_KS)} 条）**")
        lines.append("")
        for outcome in misses:
            expected = "、".join(outcome.case.expected)
            got = "、".join(
                f"{hit.doc_id}({hit.score:.3f})" for hit in outcome.raw_hits[:3]) or "无候选"
            lines.append(f"- 「{outcome.case.query}」 期望 `{expected}`，实际前 3：{got}")
        lines.append("")

    leaks = result["leaks"][:badcase_limit]
    if leaks:
        lines.append("**超纲问题却命中了知识（该拒答没拒）**")
        lines.append("")
        for outcome in leaks:
            hit = outcome.hits[0]
            lines.append(
                f"- 「{outcome.case.query}」 → `{hit.doc_id}`（{hit.score:.3f}）")
        lines.append("")

    if not misses and not leaks:
        lines.append("没有 badcase。")
        lines.append("")
    return "\n".join(lines)


def _jsonable(result: dict) -> dict:
    """去掉 Outcome 对象，只留可序列化的部分。"""
    payload = {k: v for k, v in result.items() if k not in {"misses", "leaks", "outcomes"}}
    payload["misses"] = [
        {"query": o.case.query, "expected": list(o.case.expected),
         "category": o.case.category,
         "top3": [{"doc_id": h.doc_id, "score": round(h.score, 4)}
                  for h in o.raw_hits[:3]]}
        for o in result["misses"]
    ]
    payload["leaks"] = [
        {"query": o.case.query, "hit": o.hits[0].doc_id,
         "score": round(o.hits[0].score, 4)}
        for o in result["leaks"]
    ]
    return payload


def render_threshold_section(outcomes: list[Outcome]) -> str:
    """门槛该定多少：先看分数分布，再看各门槛下的召回/拒答权衡。"""
    distribution = score_distribution(outcomes)
    sweep = threshold_sweep(outcomes)
    lines = ["## 门槛（min_score）怎么定", ""]

    inside = distribution["in_scope"]
    outside = distribution["out_of_scope"]
    if inside:
        lines.append(f"- 知识库内问题的 top1 分数：{inside['min']} ~ {inside['max']}"
                     f"（中位 {inside['p50']}）")
    if outside:
        lines.append(f"- 超纲问题的 top1 分数：{outside['min']} ~ {outside['max']}"
                     f"（中位 {outside['p50']}）")
        # 两个分布重叠越多，单靠分数门槛就越难区分 —— 这句话本身就是重要结论
        if inside and inside["min"] < outside["max"]:
            lines.append("- ⚠️ 两个分布**有重叠**：只靠分数门槛无法完全区分，"
                         "超纲问题需要靠意图识别/提示词一起兜")
    lines.append("")
    if sweep:
        lines.append("| min_score | Recall@5 | 超纲拒答率 | 平衡分 |")
        lines.append("| --- | --- | --- | --- |")
        for row in sweep:
            refusal = row["refusal_rate"]
            lines.append(
                f"| {row['min_score']} | {row['recall@5'] * 100:.1f}% | "
                f"{'—' if refusal is None else f'{refusal * 100:.1f}%'} | "
                f"{row['balanced']:.3f} |")
        lines.append("")
        best = max(sweep, key=lambda row: (row["balanced"], -row["min_score"]))
        lines.append(f"**建议**：`min_score ≈ {best['min_score']}`"
                     f"（平衡分最高 {best['balanced']:.3f}）。"
                     "数字随 embedding 模型而变，换模型后请重跑本节。")
        lines.append("")
    return "\n".join(lines)


# ============================================================ CLI
async def _run(args: argparse.Namespace) -> int:
    from ws.knowledge.corpus import load_corpus

    cases = load_eval_set()
    docs = load_corpus()
    kinds = [part.strip() for part in args.kinds.split(",") if part.strip()]

    use_hash = args.embedding == "hash" or (
        args.embedding == "auto" and args.backend == "memory")
    if use_hash:
        embedding = HashingEmbedding()
        embedding_note = "字符 bigram 哈希向量（离线、deterministic）"
    else:
        from ws.knowledge.embedding import get_embedding_backend

        embedding = get_embedding_backend()
        dim = await embedding.ensure_dim()
        embedding_note = f"{type(embedding).__name__}（dim={dim}）"

    backend_note = ("内存后端" if args.backend == "memory"
                    else "真实 pgvector")
    print(f"评测集：{len(cases)} 条（语料 {len(docs)} 条）")
    print(f"后端：{backend_note} + {embedding_note}")
    print(f"kinds：{kinds or 'all'} | min_score：{args.min_score}")
    print()

    if args.backend == "db":
        # ws.utils.database 的 engine/session_factory 是懒初始化的，
        # 应用启动时会调它；评测脚本直连数据库，必须自己先初始化
        from ws.utils import database

        database.init_db_engine()

    if args.reindex:
        if args.backend != "db":
            print("（--reindex 只在 --backend db 时生效，已忽略）")
        else:
            from ws.knowledge import store

            dim = await embedding.ensure_dim()
            await store.ensure_schema(dim)
            rows: list[store.KnowledgeRow] = []
            for start in range(0, len(docs), 10):
                batch = docs[start:start + 10]
                vectors = await embedding.embed([doc.embedding_text for doc in batch])
                rows.extend(
                    store.KnowledgeRow(
                        doc_id=doc.doc_id, kind=doc.kind, title=doc.title,
                        content=doc.content, aliases=doc.aliases,
                        source=doc.source, embedding=vector)
                    for doc, vector in zip(batch, vectors))
            await store.replace_all(rows)
            print(f"已用当前 embedding 后端重建知识索引（--reindex，{len(rows)} 条）")
            print()

    configs = (SWEEP_CONFIGS if args.sweep else
               [(args.label, {"vector_weight": args.vector_weight,
                              "keyword_weight": args.keyword_weight,
                              "keyword_mode": args.keyword_mode,
                              "include_aliases": not args.no_aliases})])

    collected: dict[str, list[Outcome]] = {}
    results: dict[str, dict] = {}
    for label, config in configs:
        if args.backend == "memory":
            retriever = MemoryRetriever(docs, embedding, **config)
            await retriever.prepare()
        else:
            retriever = make_db_retriever(kinds=kinds or ["faq", "policy"],
                                          embedding=embedding, **config)
        # 一次检索、多个门槛复用：阈值扫描不需要重复打库
        outcomes = await collect(cases, retriever, top_n=args.top_n)
        collected[label] = outcomes
        results[label] = summarize(outcomes, min_score=args.min_score)

    # 对比表：多配置时先给总览
    if len(results) > 1:
        print("## 检索配置对比")
        print()
        print("| 配置 | " + " | ".join(
            [f"Recall@{k}" for k in DEFAULT_KS] + ["MRR", "超纲拒答率"]) + " |")
        print("| --- | " + " | ".join(["---"] * (len(DEFAULT_KS) + 2)) + " |")
        for label, result in results.items():
            cells = [f"{result['recall'][f'recall@{k}'] * 100:.1f}%" for k in DEFAULT_KS]
            cells.append(f"{result['mrr']:.3f}")
            refusal = result["refusal_rate"]
            cells.append("—" if refusal is None else f"{refusal * 100:.1f}%")
            print(f"| {label} | " + " | ".join(cells) + " |")
        print()

    for label, result in results.items():
        print(render_markdown(result, label=label, badcase_limit=args.badcases))

    # 门槛分析默认看第一个配置（对比模式下就是"现状"那一组）
    primary = next(iter(collected))
    print(render_threshold_section(collected[primary]))

    if args.markdown:
        payload = "\n".join(
            render_markdown(result, label=label, badcase_limit=args.badcases)
            for label, result in results.items())
        payload += "\n" + render_threshold_section(collected[primary])
        Path(args.markdown).write_text(payload, encoding="utf-8")
        print(f"已写入 markdown：{args.markdown}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({label: _jsonable(result) for label, result in results.items()},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 JSON：{args.json}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 检索质量评测")
    parser.add_argument("--backend", choices=("memory", "db"), default="memory",
                        help="memory=离线可复现（默认）；db=真实 pgvector")
    parser.add_argument("--embedding", choices=("auto", "hash", "configured"),
                        default="auto",
                        help="auto：memory 用哈希向量、db 用配置里的 embedding 后端")
    parser.add_argument("--sweep", action="store_true", help="跑多组检索配置并输出对比表")
    parser.add_argument("--label", default="当前配置")
    parser.add_argument("--vector-weight", type=float, default=0.7)
    parser.add_argument("--keyword-weight", type=float, default=0.3)
    parser.add_argument("--keyword-mode", default="similarity",
                        choices=("none", "similarity", "word_similarity"))
    parser.add_argument("--min-score", type=float, default=settings.knowledge_min_score)
    parser.add_argument("--top-n", type=int, default=RETRIEVE_N)
    parser.add_argument("--kinds", default="faq,policy")
    parser.add_argument("--no-aliases", action="store_true",
                        help="字面分不包含别名（用于对比别名带来的收益）")
    parser.add_argument("--reindex", action="store_true",
                        help="（仅 --backend db）先按当前 embedding 后端重建知识索引")
    parser.add_argument("--badcases", type=int, default=8)
    parser.add_argument("--json", dest="json", default=None)
    parser.add_argument("--markdown", dest="markdown", default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
