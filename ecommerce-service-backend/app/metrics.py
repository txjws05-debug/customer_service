"""中台侧的 Prometheus 指标导出。

与 Agent 侧 `ws/metrics.py` 是同一套实现、同一套文本格式，刻意不抽公共包：
两个服务各自独立部署、镜像不共享代码，抽出去反而要额外维护一层同步。
格式一致性靠测试守，不靠共享模块。

为什么不引 `prometheus_client`：这台机器装包不稳，而文本格式本身很简单 ——
计数器是累加，直方图是「桶 + 总和 + 次数」，手写比引依赖更可控，也更容易测。

两个刻意的取舍：
- 只做 counter / gauge / histogram；
- 路径标签必须收敛：`/shop/orders/SO2026…` 这种原样进标签，几个请求就能把内存吃光。
"""

from __future__ import annotations

import threading
from collections import defaultdict

_LOCK = threading.Lock()

# 秒。中台以 10~200ms 为主，留到 30s 是为了兜住慢查询
BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)

_COUNTERS: dict[tuple[str, tuple], float] = defaultdict(float)
_GAUGES: dict[tuple[str, tuple], float] = {}
_HIST: dict[tuple[str, tuple], dict] = {}

_HELP = {
    "http_requests_total": ("counter", "HTTP 请求数（按方法/路径/状态）"),
    "http_request_duration_seconds": ("histogram", "HTTP 请求耗时（秒）"),
    "http_requests_in_flight": ("gauge", "当前处理中的请求数"),
    "audit_log_write_failed_total": ("counter", "审计落库失败次数（不应大于 0）"),
    "build_info": ("gauge", "构建信息，恒为 1"),
}

# 精确匹配的入口路径
KNOWN_PATHS = {
    "/shop/products", "/shop/categories", "/shop/orders",
    "/shop/admin/orders", "/shop/admin/stats", "/shop/admin/audit",
    "/health", "/metrics",
}
# 带 id 的路径统一折叠，避免标签基数失控
# 顺序即优先级：更具体的写前面。
# admin 下的发货/退款/改库存是审计最关心的动作，不能全折叠成 /shop/admin/*。
PREFIX_LABELS = {
    "/shop/admin/orders/": "/shop/admin/orders/*",
    "/shop/admin/skus/": "/shop/admin/skus/*",
    "/shop/admin/reviews/": "/shop/admin/reviews/*",
    "/shop/admin/coupons": "/shop/admin/coupons",
    "/shop/users/": "/shop/users/*",
    "/shop/orders/": "/shop/orders/*",
    "/shop/products/": "/shop/products/*",
    "/shop/after-sales/": "/shop/after-sales/*",
    "/shop/admin/": "/shop/admin/*",
}


def normalize_path(path: str) -> str:
    if path in KNOWN_PATHS:
        return path
    for prefix, label in PREFIX_LABELS.items():
        if path.startswith(prefix):
            return label
    return "other"


def inc(name: str, labels: dict | None = None, value: float = 1.0) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _LOCK:
        _COUNTERS[key] += value


def set_gauge(name: str, value: float, labels: dict | None = None) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _LOCK:
        _GAUGES[key] = value


def add_gauge(name: str, delta: float, labels: dict | None = None) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _LOCK:
        _GAUGES[key] = _GAUGES.get(key, 0.0) + delta


def observe(name: str, value: float, labels: dict | None = None) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _LOCK:
        slot = _HIST.setdefault(key, {"count": 0, "sum": 0.0,
                                      "buckets": defaultdict(int)})
        slot["count"] += 1
        slot["sum"] += value
        for bound in BUCKETS:
            if value <= bound:
                slot["buckets"][bound] += 1


def reset() -> None:
    """清空所有指标（测试用）。"""
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()
        _HIST.clear()


def _fmt(value: float) -> str:
    return f"{value:g}"


def _labels(pairs: tuple) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in pairs)
    return "{" + inner + "}"


def render() -> str:
    lines: list[str] = []
    with _LOCK:
        for name in sorted({key[0] for key in list(_COUNTERS) + list(_GAUGES) + list(_HIST)}):
            kind, help_text = _HELP.get(name, ("counter", name))
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")

            for (metric, pairs), value in sorted(_COUNTERS.items()):
                if metric == name:
                    lines.append(f"{name}{_labels(pairs)} {_fmt(value)}")
            for (metric, pairs), value in sorted(_GAUGES.items()):
                if metric == name:
                    lines.append(f"{name}{_labels(pairs)} {_fmt(value)}")
            for (metric, pairs), slot in sorted(_HIST.items()):
                if metric != name:
                    continue
                # observe() 里已经按「值 <= 上界」累加过，这里直接输出，不能再累加
                for bound in BUCKETS:
                    bucket_labels = tuple(sorted(pairs + (("le", _fmt(bound)),)))
                    lines.append(f"{name}_bucket{_labels(bucket_labels)} "
                                 f"{slot['buckets'].get(bound, 0)}")
                inf_labels = tuple(sorted(pairs + (("le", "+Inf"),)))
                lines.append(f"{name}_bucket{_labels(inf_labels)} {slot['count']}")
                lines.append(f"{name}_count{_labels(pairs)} {slot['count']}")
                lines.append(f"{name}_sum{_labels(pairs)} {slot['sum']:.6f}")
    return "\n".join(lines) + "\n"


# 恒定 1 的 gauge：让「哪次构建在跑」和指标出现在同一个响应里
set_gauge("build_info", 1, {"service": "customer-service-ecommerce"})
