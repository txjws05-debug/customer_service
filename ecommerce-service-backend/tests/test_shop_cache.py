"""商品缓存的测试（Redis 只加速读，PostgreSQL 仍是唯一事实来源）。

用内存 stub 代替真实 Redis：要验证的是我们自己的缓存语义
（版本作废、命中率统计、降级、以及**库存不进缓存**），不是 Redis 本身。

最重要的一条是 test_live_stock_is_never_cached：如果哪天有人图省事把库存
一起缓存了，页面上就会显示有货、下单却提示库存不足 —— 这里用断言拦住它。
"""

from __future__ import annotations

import pytest

from app import cache
from app.config import settings


def data_of(response) -> dict:
    """取出 ApiResponse 信封里的 data（与其它测试文件保持一致的小工具）。"""
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


class FakeRedis:
    """只实现我们用到的四个操作；TTL 不失效（测试里靠版本号验证作废）。"""

    def __init__(self, fail: bool = False):
        self.store: dict[str, str] = {}
        self.fail = fail
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("redis 崩了")

    def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    def set(self, key, value, ex=None):  # noqa: A003 - 与 redis-py 同名
        self._maybe_fail()
        self.store[key] = value

    def incr(self, key):
        self._maybe_fail()
        self.store[key] = str(int(self.store.get(key, 0)) + 1)


@pytest.fixture()
def stub_cache():
    """注入 stub，测试结束后恢复成「没有缓存」并清空计数。"""
    cache.reset_stats()
    cache.configure(FakeRedis())
    yield cache.get_client()
    cache.configure(None)
    cache.reset_stats()


# ============================================================ 缓存本身
def test_loader_runs_once_then_cache_hits(stub_cache):
    calls = []

    def loader():
        calls.append(1)
        return {"value": 42}

    first = cache.cached_json("catalog", "k", 60, loader)
    second = cache.cached_json("catalog", "k", 60, loader)

    assert first == second == {"value": 42}
    assert len(calls) == 1, "第二次应该命中缓存，不再查库"
    stats = cache.stats()
    assert stats["hit"] == 1 and stats["miss"] == 1
    assert stats["hit_rate"] == 0.5


def test_bump_invalidates_only_its_own_scope(stub_cache):
    catalog_calls, dynamic_calls = [], []

    def catalog_loader():
        catalog_calls.append(1)
        return {"scope": "catalog"}

    def dynamic_loader():
        dynamic_calls.append(1)
        return {"scope": "dynamic"}

    cache.cached_json("catalog", "k", 60, catalog_loader)
    cache.cached_json("dynamic", "k", 60, dynamic_loader)

    # 下架/改价这类写操作只作废 catalog，不该把 dynamic 也一起清掉
    cache.bump("catalog")

    cache.cached_json("catalog", "k", 60, catalog_loader)   # 应该重新查库
    cache.cached_json("dynamic", "k", 60, dynamic_loader)   # 应该仍然命中

    assert len(catalog_calls) == 2
    assert len(dynamic_calls) == 1


def test_cache_disabled_falls_back_to_database():
    cache.configure(None)
    calls = []
    cache.cached_json("catalog", "k", 60, lambda: calls.append(1) or {"ok": True})
    cache.cached_json("catalog", "k", 60, lambda: calls.append(1) or {"ok": True})
    stats = cache.stats()
    assert len(calls) == 2, "没有缓存时必须每次都查库"
    assert stats["bypass"] == 2
    assert stats["enabled"] is False


def test_redis_failure_degrades_and_trips_breaker():
    """Redis 抖动不能拖垮服务：失败后直接走库，并在熔断窗口内不再尝试。"""
    broken = FakeRedis(fail=True)
    cache.reset_stats()
    cache.configure(broken)
    try:
        calls = []
        result = cache.cached_json("catalog", "k", 60,
                                   lambda: calls.append(1) or {"ok": True})
        assert result == {"ok": True}
        assert len(calls) == 1
        assert cache.stats()["error"] >= 1
        assert cache.stats()["degraded"] is True

        # 熔断生效：第二次不再打 Redis（calls 不增长）
        before = broken.calls
        cache.cached_json("catalog", "k", 60, lambda: {"ok": True})
        assert broken.calls == before, "熔断窗口内不该继续尝试 Redis"
    finally:
        cache.configure(None)
        cache.reset_stats()


# ============================================================ 端到端（真库 + HTTP）
def test_cached_product_detail_still_reports_live_stock(client, stub_cache, db):
    """缓存生效，但库存必须实时。

    这条断言的意义：详情页缓存的是「静态骨架」，库存每次直连数据库盖上去。
    否则会出现「页面显示有货、下单说库存不足」。
    """
    first = data_of(client.get("/shop/products/SKU10006"))
    sku_code = first["skus"][0]["sku_code"]
    assert first["skus"][0]["stock"] != 7

    # 第二次请求应命中缓存
    data_of(client.get("/shop/products/SKU10006"))
    assert stub_cache is not None
    assert cache.stats()["hit"] >= 1, "第二次请求应当命中缓存"

    # 改库存（走运营端接口）→ 缓存里的静态骨架不变，但库存必须立刻反映出来
    data_of(client.patch(f"/shop/admin/skus/{sku_code}/stock",
                         json={"stock": 7, "reason": "缓存测试"}))
    after = data_of(client.get("/shop/products/SKU10006"))
    sku = next(s for s in after["skus"] if s["sku_code"] == sku_code)
    assert sku["stock"] == 7, "库存被缓存成了旧值 —— 这是不能接受的"


def test_cache_stats_endpoint_reports_hits(client, stub_cache):
    data_of(client.get("/shop/categories"))
    data_of(client.get("/shop/categories"))
    stats = data_of(client.get("/shop/admin/cache-stats"))
    assert stats["enabled"] is True
    assert stats["hit"] >= 1
    assert stats["total_lookups"] >= 2


def test_redis_url_is_optional():
    """没配 REDIS_URL 是合法状态（本地/CI 都这么跑），不能因此启动失败。"""
    assert hasattr(settings, "redis_url")
    assert cache.configure_from_settings() in (True, False)
    cache.configure(None)
