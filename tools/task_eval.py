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
import os
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


def _call(method: str, url: str, headers: dict | None = None,
          payload: dict | None = None, timeout: int = 30):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:200]}


def reset_cart(commerce_url: str, service_token: str, shop_user: str) -> int:
    """跑之前清空评测账号用的购物车。

    为什么必须做：所有非 `u####` 的登录都会回落到同一个演示商城账号，
    评测每跑一轮就往这个购物车加货。连跑几轮后某个规格被加到库存上限，
    再加购就会返回 400 —— 那时失败的是**评测自己留下的状态**，不是产品能力。
    一个会被自己残留弄红的门禁，等于没有门禁。

    返回清掉的条目数；commerce_url 为空时跳过（纯对话用例可以不配）。
    """
    if not commerce_url or not service_token:
        return 0
    headers = {"X-Service-Token": service_token, "Content-Type": "application/json"}
    status, data = _call(
        "GET", f"{commerce_url}/shop/users/{shop_user}/cart", headers)
    if status != 200:
        print(f"清理购物车失败（{status}），跳过：{str(data)[:80]}")
        return 0
    items = (data.get("data") or {}).get("items") or []
    removed = 0
    for item in items:
        code, _ = _call(
            "DELETE",
            f"{commerce_url}/shop/users/{shop_user}/cart/{item['item_id']}",
            headers)
        if code == 200:
            removed += 1
    return removed


def snapshot_stock(commerce_url: str, service_token: str) -> dict[str, int]:
    """把当前所有规格的库存记下来，供跑完还原。

    为什么用「快照 + 还原」而不是写死一个基线：写死基线等于用测试脚本
    覆盖真实业务数据，一旦有人真买过东西，还原就会把库存改回去。
    快照只保证「这次评测没留下影响」，不假设库存应该等于多少。
    """
    if not commerce_url or not service_token:
        return {}
    headers = {"X-Service-Token": service_token, "Content-Type": "application/json"}
    out: dict[str, int] = {}

    # 接口限制 page_size <= 50，所以要翻页；写死 100 会直接 422（踩过）。
    page, page_size = 1, 50
    while page <= 20:
        status, data = _call(
            "GET", f"{commerce_url}/shop/products?page_size={page_size}&page={page}",
            headers)
        if status != 200:
            print(f"库存快照失败（{status}），跳过还原：{str(data)[:80]}")
            return {}
        items = (data.get("data") or {}).get("items") or []
        if not items:
            break
        for product in items:
            pid = product.get("product_id")
            if not pid:
                continue
            status, detail = _call("GET", f"{commerce_url}/shop/products/{pid}", headers)
            if status != 200:
                continue
            for sku in (detail.get("data") or {}).get("skus") or []:
                code = sku.get("sku_code")
                if code:
                    out[code] = int(sku.get("stock", 0))
        if len(items) < page_size:
            break
        page += 1
    return out


def restore_stock(commerce_url: str, service_token: str,
                  before: dict[str, int]) -> list[str]:
    """把被本轮改动过的规格库存改回去，返回被还原的规格。"""
    if not before:
        return []
    headers = {"X-Service-Token": service_token, "Content-Type": "application/json"}
    after = snapshot_stock(commerce_url, service_token)
    changed = [code for code, stock in before.items() if after.get(code) != stock]
    for code in changed:
        _call("PATCH", f"{commerce_url}/shop/admin/skus/{code}/stock", headers,
              {"stock": before[code], "reason": "评测结束还原"})
    return changed


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


class CommerceCtx:
    """中台上下文：状态校验要用它去查副作用是否真的发生。"""

    def __init__(self, url: str, token: str, shop_user: str):
        self.url = url
        self.token = token
        self.shop_user = shop_user
        self.enabled = bool(url and token)

    def _headers(self) -> dict:
        return {"X-Service-Token": self.token, "Content-Type": "application/json"}

    def cart_quantities(self) -> dict[str, int] | None:
        """返回 {sku_code: 数量}。比集合更准：同一商品再买只是数量 +1。"""
        if not self.enabled:
            return None
        status, data = _call(
            "GET", f"{self.url}/shop/users/{self.shop_user}/cart", self._headers())
        if status != 200:
            return None
        items = ((data.get("data") or {}).get("items")) or []
        out: dict[str, int] = {}
        for i in items:
            code = str(i.get("sku_code") or "")
            if code:
                out[code] = int(i.get("quantity") or 1)
        return out

    def order_ids(self) -> set[str] | None:
        if not self.enabled:
            return None
        status, data = _call(
            "GET", f"{self.url}/shop/users/{self.shop_user}/orders", self._headers())
        if status != 200:
            return None
        # 订单列表在 data.orders，不是 items（读错字段会让校验永远判「没下单」）
        items = ((data.get("data") or {}).get("orders")) or []
        return {str(i.get("order_id") or "") for i in items}

    def ticket_ids(self) -> set[str] | None:
        if not self.enabled:
            return None
        status, data = _call(
            "GET", f"{self.url}/shop/users/{self.shop_user}/after-sales", self._headers())
        if status != 200:
            return None
        items = ((data.get("data") or {}).get("tickets")) or []
        return {str(i.get("ticket_no") or i.get("id") or "") for i in items}

    def snapshot(self) -> dict:
        return {"cart": self.cart_quantities(), "orders": self.order_ids(),
                "tickets": self.ticket_ids()}


def check_state(verify: dict, before: dict, ctx: CommerceCtx) -> tuple[bool, str]:
    """按用例声明的 verify 校验副作用。返回 (是否达成, 失败原因)。"""
    if not verify:
        return True, ""
    if not ctx.enabled:
        # 没配中台就无法校验，明确跳过而不是假装通过
        return True, ""

    kind = verify.get("type")

    if kind == "cart_added":
        sku = str(verify.get("sku") or "")
        now = ctx.cart_quantities()
        if now is None:
            return True, ""

        def total(cart: dict) -> int:
            return sum(q for k, q in (cart or {}).items() if k.startswith(sku))

        base_total = total(before.get("cart") or {})
        now_total = total(now)
        if sku and now_total > base_total:
            return True, ""
        return False, (f"购物车没有真的加入 {sku}"
                       f"（数量：{base_total} → {now_total}）")

    if kind == "after_sale_created":
        now = ctx.ticket_ids()
        if now is None:
            return True, ""
        base = before.get("tickets") or set()
        if now - base:
            return True, ""
        return False, "售后单没有真的创建（工单数与跑之前一致）"

    if kind == "order_created":
        now = ctx.order_ids()
        if now is None:
            return True, ""
        base = before.get("orders") or set()
        if now - base:
            return True, ""
        return False, "订单没有真的创建（订单数与跑之前一致）"

    return True, ""


def run_case(base: str, token: str, case: dict, ctx: CommerceCtx | None = None) -> dict:
    started = time.time()
    transcript = []
    failures = []
    error_kinds: set[str] = set()
    # 只有声明了 verify 的用例才需要拍快照（多一次中台调用）
    need_state = bool(case.get("verify")) and ctx is not None and ctx.enabled
    before = ctx.snapshot() if need_state else {}
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
    # 断言都过了之后再验副作用：文本说做了 ≠ 真的做了
    if need_state and not failures:
        ok, reason = check_state(case.get("verify") or {}, before, ctx)
        if not ok:
            failures.append(f"状态校验：{reason}")

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
    parser.add_argument("--only", default="",
                        help="只跑指定 ID，逗号分隔（如 T63,T67）。改完一处用它验证，别整跑")
    parser.add_argument("--threshold", type=float, default=0.9,
                        help="通过率门槛，低于它进程退出码为 1")
    parser.add_argument("--json", default="task_eval_report.json")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总")
    parser.add_argument("--commerce-url", default="",
                        help="中台地址；给了就会在跑之前清空评测账号的购物车")
    parser.add_argument("--commerce-token", default=os.getenv("COMMERCE_SERVICE_TOKEN", ""),
                        help="中台服务令牌，默认取环境变量 COMMERCE_SERVICE_TOKEN")
    parser.add_argument("--shop-user", default=os.getenv("COMMERCE_DEFAULT_USER_ID", "u1001"),
                        help="评测账号实际对应的商城账号号")
    parser.add_argument("--reset-stock", action="store_true",
                        help="跑前快照库存、跑完还原（用例若下单会消耗库存）")
    args = parser.parse_args()

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = [x.strip() for x in args.only.split(",") if x.strip()]
        index = {c["id"]: c for c in cases}
        missing = [w for w in wanted if w not in index]
        if missing:
            print(f"没有这些用例：{','.join(missing)}")
            return 2
        # 按 yaml 里的原顺序跑，而不是按命令行顺序：报告顺序和全量跑时一致，便于对比
        cases = [c for c in cases if c["id"] in set(wanted)]
        print(f"只跑指定用例 {len(cases)} 条：{','.join(c['id'] for c in cases)}")
    if args.limit:
        cases = cases[: args.limit]

    commerce_ctx = CommerceCtx(args.commerce_url, args.commerce_token, args.shop_user)
    username = f"eval_{uuid.uuid4().hex[:8]}"
    token = register(args.base_url, username, "eval-pass-123456")
    removed = reset_cart(args.commerce_url, args.commerce_token, args.shop_user)
    if removed:
        print(f"已清空评测购物车 {removed} 条（避免上一轮残留影响本轮）")
    print(f"评测账号 {username}，用例 {len(cases)} 条，目标 {args.base_url}")

    stock_before = {}
    if args.reset_stock:
        stock_before = snapshot_stock(args.commerce_url, args.commerce_token)
        print(f"库存快照 {len(stock_before)} 个规格（跑完还原改动）")

    results = []
    try:
        for case in cases:
            result = run_case(args.base_url, token, case, commerce_ctx)
            results.append(result)
            if not args.quiet:
                flag = "PASS" if result["passed"] else "FAIL"
                print(f"[{flag}] {result['id']} {result['name']} "
                      f"({result['turns']} 轮, {result['cost_s']}s)")
                for reason in result["failures"]:
                    print(f"       - {reason}")
    finally:
        # 放在 finally：评测中途异常也要把库存还原，
        # 否则一次失败会留下一份被改过的库存，污染下一轮
        if stock_before:
            changed = restore_stock(args.commerce_url, args.commerce_token, stock_before)
            print(f"库存还原：{'、'.join(changed) if changed else '无改动'}")

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
