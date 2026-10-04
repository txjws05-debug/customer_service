#!/usr/bin/env python3
"""压测脚本：给「并发下单 + 商品读路径缓存」提供真实数字。

它做三件事，每件都输出可直接粘进文档的 markdown：

1. **商品读路径**：以固定并发打商品详情与搜索接口，给出吞吐与
   P50/P95/P99，并从运营端接口读回这一轮的缓存命中率。
2. **并发下单**：先把某个 SKU 的库存压到很小的值，再让 10 个并发去抢，
   验证「只有 N 单成功、库存刚好扣到 0、绝不为负」。
3. 把两次运行的输出放在一起就能说明缓存的价值（Redis 开 / 关各跑一次）。

用法：
    # 无缓存（不设 REDIS_URL 启动服务）
    python scripts/load_test_orders.py --label "无缓存"

    # 有缓存（设了 REDIS_URL；--redis-url 用来在开始前作废旧缓存）
    python scripts/load_test_orders.py --label "Redis 缓存" \
        --redis-url redis://127.0.0.1:6379/0

注意：脚本会真的下单（会占用库存、产生订单），只对演示环境使用。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:18081"


def percentile(values: list[float], percent: float) -> float:
    """最近秩法求分位数（样本少的时候比插值更直观）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int(round(percent / 100 * len(ordered) + 0.5))
    return ordered[min(max(rank - 1, 0), len(ordered) - 1)]


def make_client(base_url: str) -> httpx.Client:
    # trust_env=False：压测是打本机/内网，绝不能被系统代理劫持
    return httpx.Client(base_url=base_url, timeout=30.0, trust_env=False)


def envelope(response: httpx.Response) -> dict:
    if response.status_code != 200:
        # 把响应体带上：接口报 400/404 时，原因通常就写在 message 里
        raise RuntimeError(
            f"{response.request.method} {response.request.url} -> "
            f"{response.status_code}：{response.text[:300]}")
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"{response.request.url} 返回业务错误：{payload}")
    return payload["data"]


def read_cache_stats(client: httpx.Client) -> dict:
    return envelope(client.get("/shop/admin/cache-stats"))


def invalidate_cache(redis_url: str | None) -> bool:
    """作废全部商品缓存：删掉两个版本号即可（旧 key 自然过期）。"""
    if not redis_url:
        return False
    try:
        import redis

        connection = redis.Redis.from_url(redis_url, decode_responses=True)
        connection.delete("shop:version:catalog", "shop:version:dynamic")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  （作废缓存失败，忽略：{exc}）")
        return False


def phase_reads(client: httpx.Client, concurrency: int, total: int) -> dict:
    """商品读路径压测：详情与搜索各半，记录每次请求耗时。"""
    targets = [
        ("/shop/products/SKU10001", None),
        ("/shop/products", {"keyword": "小米"}),
    ]
    durations: list[float] = []
    errors: list[str] = []

    def one(index: int) -> None:
        path, params = targets[index % len(targets)]
        started = time.perf_counter()
        try:
            response = client.get(path, params=params)
            if response.status_code != 200:
                errors.append(f"{path} -> {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path} -> {exc}")
        finally:
            durations.append((time.perf_counter() - started) * 1000)

    before = read_cache_stats(client)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(total)))
    wall = time.perf_counter() - started
    after = read_cache_stats(client)

    lookups = after["total_lookups"] - before["total_lookups"]
    hits = after["hit"] - before["hit"]
    return {
        "requests": total,
        "concurrency": concurrency,
        "wall_seconds": wall,
        "rps": total / wall if wall else 0.0,
        "p50": percentile(durations, 50),
        "p95": percentile(durations, 95),
        "p99": percentile(durations, 99),
        "mean": statistics.fmean(durations) if durations else 0.0,
        "errors": len(errors),
        "cache_lookups": lookups,
        "cache_hits": hits,
        "cache_hit_rate": (hits / lookups) if lookups else 0.0,
        "first_request_ms": durations[0] if durations else 0.0,
    }


def phase_orders(
    client: httpx.Client, sku_code: str, stock: int, concurrency: int, users: list[str],
) -> dict:
    """并发抢购：验证不超卖。"""
    # 详情接口收的是 product_id（SKU10006），不是 sku_code（SKU10006-01）
    product_id = sku_code.split("-")[0]

    # 先读当前库存，只有不一样才调整 —— 接口会拒绝「库存没有变化」的空操作
    current = envelope(client.get(f"/shop/products/{product_id}"))
    current_stock = next(s["stock"] for s in current["skus"] if s["sku_code"] == sku_code)
    if current_stock != stock:
        envelope(client.patch(f"/shop/admin/skus/{sku_code}/stock",
                              json={"stock": stock, "reason": "压测准备"}))

    before = envelope(client.get(f"/shop/products/{product_id}"))
    before_stock = next(s["stock"] for s in before["skus"] if s["sku_code"] == sku_code)

    codes: list[int] = []
    durations: list[float] = []

    def one(index: int) -> None:
        started = time.perf_counter()
        response = client.post("/shop/orders", json={
            "user_id": users[index % len(users)],
            "items": [{"sku_code": sku_code, "quantity": 1}],
        })
        durations.append((time.perf_counter() - started) * 1000)
        codes.append(response.status_code)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(concurrency)))
    wall = time.perf_counter() - started

    after = envelope(client.get(f"/shop/products/{product_id}"))
    after_stock = next(s["stock"] for s in after["skus"] if s["sku_code"] == sku_code)

    return {
        "sku_code": sku_code,
        "stock_before": before_stock,
        "concurrency": concurrency,
        "succeeded": codes.count(200),
        "rejected_409": codes.count(409),
        "other_codes": sorted({c for c in codes if c not in (200, 409)}),
        "stock_after": after_stock,
        "oversold": after_stock < 0,
        "wall_seconds": wall,
        "p50": percentile(durations, 50),
        "p95": percentile(durations, 95),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="商品读路径与并发下单压测")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--label", default="", help="输出标题里的说明，例如「Redis 缓存」")
    parser.add_argument("--redis-url", default=None,
                        help="给了就先删两个版本号，作废已有缓存（保证冷启动数字可比）")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--read-requests", type=int, default=400)
    parser.add_argument("--order-sku", default="SKU10006-01")
    parser.add_argument("--order-stock", type=int, default=3)
    parser.add_argument("--order-concurrency", type=int, default=10)
    parser.add_argument("--users", default="u1001,u1002,u1003")
    args = parser.parse_args()

    with make_client(args.base_url) as client:
        try:
            health = client.get("/health")
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"服务不可达：{args.base_url}（{exc}）", file=sys.stderr)
            return 1

        if invalidate_cache(args.redis_url):
            print("已作废已有商品缓存")
        client.post("/shop/admin/cache-stats/reset")

        # 预热：避免把首次请求的连接建立算进分位数
        client.get("/shop/products/SKU10001")

        reads = phase_reads(client, args.concurrency, args.read_requests)
        orders = phase_orders(client, args.order_sku, args.order_stock,
                              args.order_concurrency, args.users.split(","))

    title = f"商品读路径与并发下单压测{('（' + args.label + '）') if args.label else ''}"
    print()
    print(f"## {title}")
    print()
    print(f"- 服务地址：`{args.base_url}`")
    print(f"- 商品读路径：并发 {reads['concurrency']}，共 {reads['requests']} 次请求"
          f"（商品详情与列表各半）")
    print()
    print("| 指标 | 数值 |")
    print("| --- | --- |")
    print(f"| 吞吐（req/s） | {reads['rps']:.1f} |")
    print(f"| 平均延迟 | {reads['mean']:.0f} ms |")
    print(f"| P50 / P95 / P99 | {reads['p50']:.0f} / {reads['p95']:.0f} / "
          f"{reads['p99']:.0f} ms |")
    print(f"| 缓存命中率 | {reads['cache_hit_rate'] * 100:.1f}%"
          f"（{reads['cache_hits']}/{reads['cache_lookups']} 次查缓存） |")
    print(f"| 失败请求 | {reads['errors']} |")
    print()
    print(f"- 并发下单：{orders['concurrency']} 个并发抢 "
          f"{orders['stock_before']} 件（{orders['sku_code']}）")
    print()
    print("| 指标 | 数值 |")
    print("| --- | --- |")
    print(f"| 成功下单 | {orders['succeeded']} |")
    print(f"| 因库存不足被拒（409） | {orders['rejected_409']} |")
    print(f"| 最终库存 | {orders['stock_after']}（超卖：{'是' if orders['oversold'] else '否'}） |")
    print(f"| 下单 P50 / P95 | {orders['p50']:.0f} / {orders['p95']:.0f} ms |")
    if orders["other_codes"]:
        print(f"| 其它状态码 | {orders['other_codes']} |")
    print()

    problems = []
    if reads["errors"]:
        problems.append(f"读路径有 {reads['errors']} 个失败请求")
    if orders["succeeded"] != orders["stock_before"]:
        problems.append(f"成功单数 {orders['succeeded']} != 库存 {orders['stock_before']}")
    if orders["stock_after"] != 0:
        problems.append(f"最终库存应为 0，实际 {orders['stock_after']}")
    if orders["oversold"]:
        problems.append("出现超卖（库存为负）")
    if problems:
        print("结论：**未通过** —— " + "；".join(problems))
        return 1

    print("结论：**通过** —— 库存刚好扣完、无超卖、无失败请求")
    return 0


if __name__ == "__main__":
    sys.exit(main())
