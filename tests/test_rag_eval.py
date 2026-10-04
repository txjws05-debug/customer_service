"""RAG 评测闭环的测试。

分两层：
1. **指标算得对不对**：用构造出来的排名直接验算 Recall@k / MRR / 超纲拒答率 ——
   指标算错的评测比没有评测更危险，它会让人朝错误方向调优；
2. **评测集与流程本身**：expected 里的 doc_id 必须真实存在于语料，
   以及离线后端能端到端跑完并守住一条质量底线（回归保护）。

离线后端不需要数据库也不需要 embedding API，所以这些断言在 CI 里一定能跑。
"""

from __future__ import annotations

import asyncio

from ws.knowledge import eval as rag_eval


def _outcome(query: str, expected: list[str], hits: list[tuple[str, float]],
             category: str = "direct") -> rag_eval.Outcome:
    return rag_eval.Outcome(
        case=rag_eval.EvalCase(query=query, expected=tuple(expected), category=category),
        hits=[rag_eval.Hit(doc_id=doc_id, title=doc_id, score=score)
              for doc_id, score in hits],
        raw_hits=[rag_eval.Hit(doc_id=doc_id, title=doc_id, score=score)
                  for doc_id, score in hits],
    )


# ============================================================ 指标
def test_recall_and_mrr_are_computed_correctly():
    outcomes = [
        _outcome("q1", ["a"], [("a", 0.9), ("b", 0.8)]),        # 第 1 名命中
        _outcome("q2", ["b"], [("a", 0.9), ("b", 0.8)]),        # 第 2 名命中
        _outcome("q3", ["c"], [("a", 0.9), ("b", 0.8)]),        # 没命中
    ]
    summary = rag_eval.summarize(outcomes, min_score=0.05, ks=(1, 3, 5))

    assert summary["recall"]["recall@1"] == round(1 / 3, 4)     # 只有 q1 在前 1
    assert summary["recall"]["recall@3"] == round(2 / 3, 4)     # q1、q2 在前 3
    assert summary["mrr"] == round((1.0 + 0.5 + 0.0) / 3, 4)
    assert len(summary["misses"]) == 1
    assert summary["misses"][0].case.query == "q3"


def test_min_score_gate_filters_hits_and_marks_refusal():
    """门槛是线上"没检索到"的唯一判据，必须精确：刚好等于门槛算通过。"""
    outcomes = [_outcome("q", ["a"], [("a", 0.2)])]

    just_below = rag_eval.summarize(outcomes, min_score=0.2001)
    assert just_below["recall"]["recall@5"] == 0.0
    assert just_below["misses"][0].refused is True

    exactly = rag_eval.summarize(outcomes, min_score=0.2)
    assert exactly["recall"]["recall@5"] == 1.0


def test_out_of_scope_cases_measure_refusal():
    outcomes = [
        _outcome("q1", ["a"], [("a", 0.9)]),
        _outcome("股票代码是多少", [], [("policy-payment-invoice", 0.2)],
                 category="out_of_scope"),
        _outcome("天气怎么样", [], [("faq-x", 0.01)], category="out_of_scope"),
    ]
    summary = rag_eval.summarize(outcomes, min_score=0.05, ks=(1, 3, 5))

    # 一条被门槛挡住、一条没挡住
    assert summary["refusal_rate"] == 0.5
    assert len(summary["leaks"]) == 1
    assert summary["leaks"][0].case.query == "股票代码是多少"
    # 超纲用例不参与 Recall 计算
    assert summary["recall"]["recall@5"] == 1.0


def test_threshold_sweep_moves_in_the_expected_direction():
    outcomes = [
        _outcome("q1", ["a"], [("a", 0.9)]),
        _outcome("q2", ["b"], [("b", 0.3)]),
        _outcome("超纲", [], [("x", 0.4)], category="out_of_scope"),
    ]
    sweep = rag_eval.threshold_sweep(outcomes, ks=(1, 3, 5))
    assert len(sweep) >= 3

    lowest, highest = sweep[0], sweep[-1]
    assert lowest["min_score"] < highest["min_score"]
    # 门槛越高，召回越低、拒答越高
    assert highest["recall@5"] <= lowest["recall@5"]
    assert highest["refusal_rate"] >= lowest["refusal_rate"]


# ============================================================ 评测集与端到端
def test_eval_set_ids_all_exist_in_corpus():
    """expected 写错 id 的话，评测会显示"检索坏了"，其实是标注写错了。"""
    cases = rag_eval.load_eval_set()
    assert len(cases) >= 30, "评测集太小，指标没有统计意义"

    categories = {case.category for case in cases}
    assert {"direct", "colloquial", "policy", "out_of_scope"} <= categories

    out_of_scope = [c for c in cases if c.category == "out_of_scope"]
    assert out_of_scope, "必须有无标准答案的用例，否则测不出「硬扯一条」"
    assert all(not c.expected for c in out_of_scope)
    assert all(c.expected for c in cases if c.category != "out_of_scope")


def test_offline_harness_runs_and_keeps_quality_floor():
    """离线后端端到端跑一遍：不依赖数据库/API，同时守住质量底线。"""
    from ws.knowledge.corpus import load_corpus

    cases = rag_eval.load_eval_set()
    docs = load_corpus()

    async def run() -> dict:
        retriever = rag_eval.MemoryRetriever(
            docs, rag_eval.HashingEmbedding(),
            vector_weight=0.7, keyword_weight=0.3,
            keyword_mode="similarity", include_aliases=True)
        await retriever.prepare()
        return rag_eval.summarize(
            await rag_eval.collect(cases, retriever), min_score=0.05)

    summary = asyncio.run(run())
    # 用离线哈希向量实测 Recall@5 = 100%、Recall@1 ≈ 94%，
    # 这里留出余量：只要求"别退化"，不做精确断言（换 embedding 会变）
    assert summary["recall"]["recall@5"] >= 0.85
    assert summary["recall"]["recall@1"] >= 0.7
    assert summary["mrr"] >= 0.75


def test_aliases_are_scored_and_not_leaked_into_prompt():
    """别名要参与打分，但不能出现在喂给 LLM 的正文里。"""
    from ws.knowledge.corpus import load_corpus
    from ws.knowledge.store import KnowledgeRow  # noqa: F401  仅确认字段存在

    doc = next(d for d in load_corpus() if d.aliases)
    assert doc.aliases in doc.embedding_text, "别名必须参与向量化"
    assert doc.aliases not in doc.content, "别名不该混进正文"
