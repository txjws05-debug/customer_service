"""极简 Prometheus 指标导出。

为什么不用 prometheus_client：这台机器装不了包（PyPI 不通），而文本格式本身
很简单 —— 计数器是累加，直方图是「桶 + 总和 + 次数」，手写比引依赖更可控。

设计取舍：
- 只做 counter / gauge / histogram 三种，够用且不会写错；
- 桶边界按本项目的真实量级定（LLM 调用 2~20s，中台调用 10~200ms）；
- 路径做白名单收敛，避免 /shop/orders/<订单号> 这类高基数标签把内存打爆。
"""

from __future__ import annotations

import threading
from collections import defaultdict

_LOCK = threading.Lock()

# 秒。覆盖「中台 12ms」到「LLM 20s 超时」这两段量级
BUCKETS: tuple[float, ...] = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30)

_COUNTERS: dict[tuple[str, tuple], float] = defaultdict(float)
_GAUGES: dict[tuple[str, tuple], float] = {}
_HIST: dict[tuple[str, tuple], dict] = {}
_HELP = {
    "http_requests_total": ("counter", "HTTP 请求数（按方法/路径/状态）"),
    "http_request_duration_seconds": ("histogram", "HTTP 请求耗时（秒）"),
    "http_requests_in_flight": ("gauge", "当前处理中的请求数"),
    "build_info": ("gauge", "构建信息，恒为 1"),
}
# 只统计这些入口路径；其余归到 "other"，防止标签基数失控
KNOWN_PATHS = {"/api/chat", "/api/chat/stream", "/api/auth/login",
               "/api/auth/register", "/health", "/metrics"}


def normalize_path(path: str) -> str:
    return path if path in KNOWN_PATHS else "other"


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
        slot = _HIST.setdefault(
            key, {"buckets": defaultdict(int), "sum": 0.0, "count": 0})
        slot["sum"] += value
        slot["count"] += 1
        for bound in BUCKETS:
            if value <= bound:
                slot["buckets"][bound] += 1


def _fmt_labels(pairs: tuple) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in pairs)
    return "{" + inner + "}"


def render() -> str:
    """输出 Prometheus 文本格式（v0.0.4）。同名字指标只写一次 TYPE。"""
    lines: list[str] = []
    with _LOCK:
        counters = dict(_COUNTERS)
        gauges = dict(_GAUGES)
        hists = {k: {"buckets": dict(v["buckets"]),
                     "sum": v["sum"], "count": v["count"]}
                 for k, v in _HIST.items()}

    emitted: set[str] = set()
    for (name, pairs), value in sorted(counters.items()):
        if name not in emitted:
            kind, doc = _HELP.get(name, ("counter", name))
            lines += [f"# HELP {name} {doc}", f"# TYPE {name} {kind}"]
            emitted.add(name)
        lines.append(f"{name}{_fmt_labels(pairs)} {value:g}")

    for (name, pairs), value in sorted(gauges.items()):
        if name not in emitted:
            kind, doc = _HELP.get(name, ("gauge", name))
            lines += [f"# HELP {name} {doc}", f"# TYPE {name} {kind}"]
            emitted.add(name)
        lines.append(f"{name}{_fmt_labels(pairs)} {value:g}")

    for (name, pairs), slot in sorted(hists.items()):
        if name not in emitted:
            _, doc = _HELP.get(name, ("histogram", name))
            lines += [f"# HELP {name} {doc}", f"# TYPE {name} histogram"]
            emitted.add(name)
        # observe() 里已经把「值 <= 上界」的桶全部 +1，这里直接输出，
        # 不能再次累加 —— 否则 1.5s 的样本会让 10/20/30 三个桶都多算一遍
        for bound in BUCKETS:
            labels = tuple(sorted(pairs + (("le", f"{bound:g}"),)))
            lines.append(
                f"{name}_bucket{_fmt_labels(labels)} {slot['buckets'].get(bound, 0)}")
        total = slot["count"]
        labels = pairs + (("le", "+Inf"),)
        lines.append(f"{name}_bucket{_fmt_labels(tuple(sorted(labels)))} {total}")
        lines.append(f"{name}_sum{_fmt_labels(pairs)} {slot['sum']:.6f}")
        lines.append(f"{name}_count{_fmt_labels(pairs)} {total}")

    lines.append("# EOF")
    return "\n".join(lines) + "\n"


def reset() -> None:
    """测试用：清空所有指标。"""
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()
        _HIST.clear()


# 恒定 1 的 gauge：让「哪次构建在跑」和指标在同一个响应里可见
set_gauge("build_info", 1, {"service": "customer-service-agent"})
