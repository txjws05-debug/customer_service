"""指标导出：格式正确、桶不重复累加、端点带令牌校验。

这里不依赖 prometheus_client（这台机器装不了包），所以格式正确性必须自己测 ——
写错一格，Prometheus 抓过去就是一堆坏数据，而且不会报错。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ws import metrics


@pytest.fixture(autouse=True)
def _clean():
    metrics.reset()
    yield
    metrics.reset()


def test_counter_and_labels():
    metrics.inc("http_requests_total",
                {"method": "GET", "path": "/api/chat", "status": "200"})
    metrics.inc("http_requests_total",
                {"method": "GET", "path": "/api/chat", "status": "200"})
    text = metrics.render()
    assert '# TYPE http_requests_total counter' in text
    assert 'http_requests_total{method="GET",path="/api/chat",status="200"} 2' in text


def test_histogram_buckets_are_cumulative_without_double_counting():
    metrics.observe("t_seconds", 0.2)
    metrics.observe("t_seconds", 1.5)
    text = metrics.render()
    # 0.2 落进 le=0.25；1.5 落进 le=2。桶必须是累积值，且不能被再累加一次
    assert 't_seconds_bucket{le="0.25"} 1' in text
    assert 't_seconds_bucket{le="2"} 2' in text
    assert 't_seconds_bucket{le="30"} 2' in text
    assert 't_seconds_count 2' in text
    assert 't_seconds_sum 1.700000' in text


def test_path_label_is_collapsed_for_unknown_paths():
    assert metrics.normalize_path("/api/chat") == "/api/chat"
    assert metrics.normalize_path("/shop/orders/SO202610281019307902D3") == "other"


def test_metrics_endpoint_serves_text():
    from fastapi.testclient import TestClient

    from ws.api.app import app

    client = TestClient(app)
    metrics.inc("http_requests_total", {"method": "GET", "path": "/api/chat", "status": "200"})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text
    assert resp.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_requires_token_when_configured(monkeypatch):
    from fastapi.testclient import TestClient

    from ws.api import app as app_module

    monkeypatch.setattr(app_module, "settings",
                        SimpleNamespace(metrics_token="secret-metrics"))
    client = TestClient(app_module.app)

    assert client.get("/metrics").status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer secret-metrics"})
    assert ok.status_code == 200
