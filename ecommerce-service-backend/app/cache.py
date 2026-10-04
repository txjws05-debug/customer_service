"""商品读路径的 Redis 缓存（cache-aside）。

四条必须守住的规矩：

1. **PostgreSQL 是唯一事实来源。** 缓存只加速读，绝不承接写：下单、支付、
   收货、库存调整一律直接写库，缓存对它们来说只是「可以作废的副本」。
   任何一处写操作都不能依赖缓存成功。
2. **强一致字段不进缓存。** SKU 的 `stock`（以及下单时读的价格）永远直连数据库 ——
   商品详情页缓存的是「静态骨架」，每次请求再把实时库存盖上去，
   否则会出现「页面显示有货、下单说库存不足」这种最讨人厌的错。
3. **Redis 挂了不能影响服务。** 连不上就当作没有缓存，直接走库；
   连续失败会触发 30 秒熔断，避免每个请求都卡在连接超时上（也避免刷日志）。
4. **按数据时效性分两个版本号**，写操作只 INCR 对应版本，旧 key 自然过期，
   不用去枚举删除：
   - `catalog`：只有运营改商品才会变（标题/描述/属性/品牌/类目/规格价格）；
   - `dynamic`：下单、评价、调库存都会变（库存状态/销量/评分/搜索结果）。

缓存里存的是「响应模型的 JSON 形态」（`model_dump(mode="json")`），
命中时再用 `model_validate` 还原 —— 命中与未命中走的是同一条校验路径。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("ecommerce.cache")

# 两级数据的 TTL（秒）
TTL_CATALOG = 600
TTL_DYNAMIC = 30

VERSION_KEY = "shop:version:{scope}"
_KNOWN_SCOPES = ("catalog", "dynamic")

# 连续失败后的熔断时长：Redis 抖动时不要让每个请求都等连接超时
_BREAKER_SECONDS = 30

_lock = threading.Lock()
_client: Any = None
_fail_until = 0.0
_warned = False
_stats = {"hit": 0, "miss": 0, "bypass": 0, "error": 0}


# ============================================================ 配置
def configure(client: Any) -> None:
    """注入 Redis 客户端（测试里注入内存 stub，启动时注入真实客户端）。"""
    global _client, _fail_until, _warned
    with _lock:
        _client = client
        _fail_until = 0.0
        _warned = False


def get_client() -> Any:
    """当前注入的客户端（不做可用性判断，测试用来确认注入是否生效）。"""
    return _client


def configure_from_settings() -> bool:
    """按 REDIS_URL 建客户端。未配置就保持 None（等价于「没有缓存」）。"""
    from app.config import settings

    url = (settings.redis_url or "").strip()
    if not url:
        logger.info("未配置 REDIS_URL，商品缓存关闭（直接读 PostgreSQL）")
        configure(None)
        return False

    try:
        import redis  # 延迟导入：没装 redis 包时服务照样能跑

        configure(redis.Redis.from_url(
            url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2))
        logger.info("商品缓存已启用：%s", url.split("@")[-1])
        return True
    except Exception as exc:  # noqa: BLE001 - 缓存是可选能力，不能拦住启动
        logger.warning("初始化 Redis 失败，商品缓存关闭：%s", exc)
        configure(None)
        return False


# ============================================================ 内部
def _trip(exc: Exception) -> None:
    """熔断：一段时间内不再尝试 Redis。"""
    global _fail_until, _warned
    _stats["error"] += 1
    _fail_until = time.monotonic() + _BREAKER_SECONDS
    if not _warned:
        logger.warning("Redis 访问失败，%s 秒内降级为直连数据库：%s", _BREAKER_SECONDS, exc)
        _warned = True


def _usable_client():
    if _client is None or time.monotonic() < _fail_until:
        return None
    return _client


def version(scope: str) -> int:
    """当前版本号。拿不到就返回 0（缓存 key 依然稳定，只是可能命中旧数据，
    而旧数据最多多活一个 TTL）。"""
    client = _usable_client()
    if client is None:
        return 0
    try:
        return int(client.get(VERSION_KEY.format(scope=scope)) or 0)
    except Exception as exc:  # noqa: BLE001
        _trip(exc)
        return 0


def bump(scope: str) -> None:
    """写操作后作废对应缓存。**失败不影响业务**：调用方在事务提交后尽力调用。"""
    if scope not in _KNOWN_SCOPES:
        raise ValueError(f"未知的缓存作用域：{scope}")
    client = _usable_client()
    if client is None:
        return
    try:
        client.incr(VERSION_KEY.format(scope=scope))
    except Exception as exc:  # noqa: BLE001
        _trip(exc)


def cached_json(scope: str, key_suffix: str, ttl: int, loader: Callable[[], Any]) -> Any:
    """cache-aside：命中直接返回，未命中调用 loader 并写入缓存。

    Redis 不可用时**直接调用 loader**，调用方无需感知。
    """
    client = _usable_client()
    if client is None:
        _stats["bypass"] += 1
        return loader()

    key = f"shop:{scope}:v{version(scope)}:{key_suffix}"
    try:
        raw = client.get(key)
        if raw is not None:
            _stats["hit"] += 1
            return json.loads(raw)
        _stats["miss"] += 1
    except Exception as exc:  # noqa: BLE001
        _trip(exc)
        _stats["bypass"] += 1
        return loader()

    value = loader()
    try:
        client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except Exception as exc:  # noqa: BLE001
        _trip(exc)
    return value


def stats() -> dict:
    """给运营端看命中率，也用来给 README 提供真实数字。"""
    total = _stats["hit"] + _stats["miss"]
    return {
        **_stats,
        "total_lookups": total,
        "hit_rate": round(_stats["hit"] / total, 4) if total else 0.0,
        "enabled": _client is not None,
        "degraded": _client is not None and time.monotonic() < _fail_until,
        "catalog_version": version("catalog"),
        "dynamic_version": version("dynamic"),
    }


def reset_stats() -> None:
    """压测/测试用：清空计数，不改变连接状态。"""
    for name in _stats:
        _stats[name] = 0
