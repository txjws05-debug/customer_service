# -*- coding: utf-8 -*-
"""裸模型基线：同一批用例，直接问模型，不经过客服系统。

用途：回答「你这个系统和直接调大模型有什么区别」。

对照条件：
- 同样的 40 条用例、同样的断言、同样的模型；
- 只给一个通用客服人设，不给工具、不给知识库、不给订单数据；
- 用户点选商品时，把商品标题拼进消息（真实用户看得到商品卡）。

所以这个基线衡量的是「把业务直接丢给模型」能做到什么程度。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request

import httpx
import yaml

BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
CASES = os.getenv("CASES", "tools/task_cases.yaml")
OUT = os.getenv("OUT", "bare_model_report.json")

SYSTEM = (
    "你是一名电商店铺的客服助手，用中文自然地回答顾客的问题。\n"
    "店铺售卖手机数码类商品，支持七天无理由退货（商品需未拆封）、可开具电子发票、"
    "正常情况下 48 小时内发货。"
)


SHOP_USER = os.getenv("COMMERCE_DEFAULT_USER_ID", "u1001")
SHOP_URL = os.getenv("COMMERCE_URL", "")
SHOP_TOKEN = os.getenv("COMMERCE_SERVICE_TOKEN", "")


def _shop(path: str):
    """查中台。裸模型没有登录态，这里用服务令牌代查演示账号。"""
    if not SHOP_URL or not SHOP_TOKEN:
        return None
    req = urllib.request.Request(
        f"{SHOP_URL}{path}",
        headers={"X-Service-Token": SHOP_TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode() or "{}")
    except Exception:
        return None


def snapshot() -> dict:
    cart = _shop(f"/shop/users/{SHOP_USER}/cart")
    orders = _shop(f"/shop/users/{SHOP_USER}/orders")
    c = {}
    for i in ((cart or {}).get("data") or {}).get("items") or []:
        code = str(i.get("sku_code") or "")
        if code:
            c[code] = int(i.get("quantity") or 1)
    o = {str(i.get("order_id") or "") for i in ((orders or {}).get("data") or {}).get("items") or []}
    return {"cart": c, "orders": o}


def check_state(verify: dict, before: dict) -> tuple[bool, str]:
    if not verify or not SHOP_URL:
        return True, ""
    kind = verify.get("type")
    if kind == "cart_added":
        sku = str(verify.get("sku") or "")
        now = snapshot()["cart"]

        def total(cart: dict) -> int:
            return sum(q for k, q in (cart or {}).items() if k.startswith(sku))

        base_total = total(before.get("cart") or {})
        now_total = total(now)
        if sku and now_total > base_total:
            return True, ""
        return False, (f"购物车没有真的加入 {sku}"
                       f"（数量：{base_total} → {now_total}）")
    if kind == "order_created":
        now = snapshot()["orders"]
        base = before.get("orders") or set()
        if now - base:
            return True, ""
        return False, "订单没有真的创建（订单数与跑之前一致）"
    return True, ""


def judge(text: str, expect: dict) -> tuple[bool, str]:
    """与 task_eval.py 完全一致的三种断言。"""
    if not expect:
        return True, ""
    if "any_of" in expect and not any(w in text for w in expect["any_of"]):
        return False, f"未命中任一关键词 {expect['any_of']}"
    if "none_of" in expect:
        hit = [w for w in expect["none_of"] if w in text]
        if hit:
            return False, f"出现禁止内容 {hit}"
    if "min_length" in expect and len(text) < expect["min_length"]:
        return False, f"回复过短（{len(text)}）"
    return True, ""


async def ask(client: httpx.AsyncClient, messages: list[dict]) -> str:
    for attempt in range(3):
        try:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={"model": MODEL, "messages": messages, "temperature": 0.7},
                timeout=60.0,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"] or ""
        except Exception:
            pass
        await asyncio.sleep(2 * (attempt + 1))
    return ""


async def run_case(client: httpx.AsyncClient, case: dict) -> dict:
    messages = [{"role": "system", "content": SYSTEM}]
    failures: list[str] = []
    transcript: list[dict] = []
    need_state = bool(case.get("verify")) and bool(SHOP_URL)
    before = snapshot() if need_state else {}

    for turn in case.get("turns") or []:
        text = (turn.get("text") or "").strip()
        obj = turn.get("object")
        if obj:
            title = obj.get("title") or obj.get("id") or ""
            body = f"【顾客正在查看商品：{title}】\n{text}" if text else \
                   f"【顾客正在查看商品：{title}】\n（顾客点开了这个商品）"
        else:
            body = text
        messages.append({"role": "user", "content": body})

        reply = await ask(client, messages)
        messages.append({"role": "assistant", "content": reply})

        ok, why = judge(reply, turn.get("expect") or {})
        transcript.append({"turn": len(transcript) + 1, "user": text, "reply": reply[:400]})
        if not ok:
            failures.append(f"第 {len(transcript)} 轮：{why}")

    if need_state and not failures:
        ok, reason = check_state(case.get("verify") or {}, before)
        if not ok:
            failures.append(f"状态校验：{reason}")

    return {
        "id": case["id"],
        "name": case.get("name", ""),
        "passed": not failures,
        "failures": failures,
        "transcript": transcript,
    }


async def main() -> int:
    if not API_KEY:
        print("缺少 LLM_API_KEY", file=sys.stderr)
        return 1

    with open(CASES, encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]

    started = time.time()
    async with httpx.AsyncClient() as client:
        results = []
        for case in cases:
            r = await run_case(client, case)
            results.append(r)
            flag = "PASS" if r["passed"] else "FAIL"
            print(f"[{flag}] {r['id']} {r['name']}", flush=True)

    passed = sum(1 for r in results if r["passed"])
    report = {
        "account": "bare-model",
        "base_url": BASE_URL,
        "model": MODEL,
        "passed": passed,
        "total": len(results),
        "pass_rate": passed / len(results) if results else 0,
        "cost_s": round(time.time() - started, 1),
        "results": results,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    fails = [r["id"] for r in results if not r["passed"]]
    print(f"\n通过率 {passed}/{len(results)} = {report['pass_rate']:.1%}，"
          f"总耗时 {report['cost_s']}s")
    print("失败用例:", ",".join(fails) or "—")
    print("报告已写入", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
