#!/usr/bin/env python3
"""多轮任务评测：用脚本化对话跑真实接口，量出「对话到底能不能把事办成」。

和 `ws/knowledge/eval.py` 的区别（这也是为什么另起一个 runner 而不是复用）：
- 那边评测**检索**：给定问题，看有没有命中标注好的 doc_id，指标是 Recall/MRR；
- 这边评测**任务**：给定一串对话，看最终回复是否满足断言，指标是任务通过率。
两者的用例格式、断言方式、报告字段完全不同，硬塞进一个脚本只会互相拖累。

断言只用「关键词之一命中」这类宽松形式：LLM 的措辞每次都不一样，
断言写死一句话必然天天红；但关键词集合能稳定表达「这件事有没有被做到」。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import yaml


def _post(url: str, payload: dict, token: str | None = None, timeout: int = 60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:200]}


def register(base: str, username: str, password: str) -> str:
    status, data = _post(f"{base}/api/auth/register",
                         {"username": username, "password": password})
    if status != 200 or "access_token" not in data:
        raise SystemExit(f"注册测试账号失败：{status} {data}")
    return data["access_token"]


def reply_text(data: dict) -> str:
    messages = data.get("messages") or []
    return " ".join(str(m.get("text", "")) for m in messages)


def check(text: str, expect: dict) -> tuple[bool, str]:
    """三种断言：any_of（任一关键词）、none_of（都不能出现）、min_length。"""
    if "any_of" in expect:
        if not any(word in text for word in expect["any_of"]):
            return False, f"未命中任一关键词 {expect['any_of']}"
    if "none_of" in expect:
        hit = [word for word in expect["none_of"] if word in text]
        if hit:
            return False, f"出现了不该出现的内容 {hit}"
    if "min_length" in expect and len(text) < expect["min_length"]:
        return False, f"回复过短（{len(text)} < {expect['min_length']}）"
    return True, ""


def classify_failure(status: int, reply: str, detail: str = "") -> str:
    """区分「能力没做到」和「上游抖动」。

    两者都算失败（用户确实没拿到答案），但混在一起看通过率会误导：
    超时是外部因素，断言不中是系统能力问题，改进方向完全不同。
    """
    text = f"{reply} {detail}"
    if status == 400 and ("超时" in text or "timeout" in text.lower()):
        return "upstream_timeout"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    if status != 200:
        return "http_error"
    return "assertion"


def run_case(base: str, token: str, case: dict) -> dict:
    started = time.time()
    transcript = []
    failures = []
    error_kinds: set[str] = set()
    for index, turn in enumerate(case["turns"], 1):
        payload = {"text": turn["text"]}
        if turn.get("object"):
            payload["object"] = turn["object"]
        status, data = _post(f"{base}/api/chat", payload, token)
        text = reply_text(data) if status == 200 else ""
        transcript.append({"turn": index, "user": turn["text"],
                           "status": status, "reply": text})
        if status != 200:
            kind = classify_failure(status, text, str(data.get("detail", "")))
            error_kinds.add(kind)
            failures.append(f"第 {index} 轮 HTTP {status}（{kind}）")
            break
        ok, reason = check(text, turn.get("expect") or {})
        if not ok:
            failures.append(f"第 {index} 轮：{reason}")
    return {
        "id": case["id"],
        "name": case.get("name", case["id"]),
        "passed": not failures,
        "error_kinds": sorted(error_kinds),
        "failures": failures,
        "cost_s": round(time.time() - started, 2),
        "turns": len(transcript),
        "transcript": transcript,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="多轮任务评测")
    parser.add_argument("--base-url", default="http://127.0.0.1:18082")
    parser.add_argument("--cases", default="tools/task_cases.yaml")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    parser.add_argument("--threshold", type=float, default=0.9,
                        help="通过率门槛，低于它进程退出码为 1")
    parser.add_argument("--json", default="task_eval_report.json")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = parser.parse_args()

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.limit:
        cases = cases[: args.limit]

    username = f"eval_{uuid.uuid4().hex[:8]}"
    token = register(args.base_url, username, "eval-pass-123456")
    print(f"评测账号 {username}，用例 {len(cases)} 条，目标 {args.base_url}")

    results = []
    for case in cases:
        result = run_case(args.base_url, token, case)
        results.append(result)
        if not args.quiet:
            flag = "PASS" if result["passed"] else "FAIL"
            print(f"[{flag}] {result['id']} {result['name']} "
                  f"({result['turns']} 轮, {result['cost_s']}s)")
            for reason in result["failures"]:
                print(f"       - {reason}")

    passed = sum(1 for r in results if r["passed"])
    rate = passed / len(results) if results else 0.0
    total_cost = round(sum(r["cost_s"] for r in results), 1)
    timeouts = sum(1 for r in results if "upstream_timeout" in r["error_kinds"])
    print(f"\n通过率 {passed}/{len(results)} = {rate:.1%}，总耗时 {total_cost}s")
    if timeouts:
        print(f"其中 {timeouts} 条是上游超时（非能力缺失，可用 --json 报告里的 error_kinds 过滤）")
    print(f"账号 {username}（用例产生的订单/购物车可用该账号清理）")

    Path(args.json).write_text(json.dumps({
        "account": username,
        "base_url": args.base_url,
        "passed": passed,
        "total": len(results),
        "pass_rate": round(rate, 4),
        "cost_s": total_cost,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {args.json}")

    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
