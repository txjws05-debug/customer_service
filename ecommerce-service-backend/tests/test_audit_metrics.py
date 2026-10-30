"""审计与中台指标。

两块都容易「看着有、其实没有」：
- 审计：写了记录但记的是 anonymous（中间件挂反了），等于白做；
- 指标：格式写错，Prometheus 抓过去是一堆坏数据，而且不报错。
所以这里既测「记没记」，也测「谁被记了」和「格式对不对」。
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from app import audit, metrics

SKU = "SKU10006-01"


def _reset_stock(db, stock: int = 20) -> None:
    db.execute(text("UPDATE product_skus SET stock=:s WHERE sku_code=:c"),
               {"s": stock, "c": SKU})
    db.commit()


def _rows(db, path: str):
    db.expire_all()
    return db.execute(text(
        "SELECT actor_kind, actor, action, status FROM audit_log "
        "WHERE path = :p ORDER BY id DESC"), {"p": path}).fetchall()


# ------------------------------------------------------------------ 该不该记
def test_only_mutations_are_audited():
    assert audit.should_audit("POST", "/shop/orders")
    assert audit.should_audit("DELETE", "/shop/users/u1001/cart/1")
    # 读操作记进去只会把表刷满，没有审计价值
    assert not audit.should_audit("GET", "/shop/orders")
    # 探针不算「人的操作」
    assert not audit.should_audit("POST", "/health")
    assert not audit.should_audit("POST", "/metrics")


def test_action_label_is_low_cardinality():
    """订单号不能进标签，否则一个月能写出几十万个不同 action。"""
    assert audit.action_of("POST", "/shop/orders") == "POST /shop/orders"
    assert audit.action_of("POST", "/shop/orders/SO20261030090000ABCD") == \
        "POST /shop/orders/*"
    assert audit.action_of("patch", "/shop/users/u1001/cart") == \
        "PATCH /shop/users/*"
    # 运营动作要能分开聚合：发货和改库存是两回事
    assert audit.action_of("POST", "/shop/admin/orders/SO1/ship") == \
        "POST /shop/admin/orders/*"
    assert audit.action_of("POST", "/shop/admin/skus/SKU1/stock") == \
        "POST /shop/admin/skus/*"


# ------------------------------------------------------------------ 落库与查询
def test_record_and_query(db):
    audit.record(trace_id="t-audit-1", actor_kind="operator", actor="operator",
                 method="POST", path="/shop/admin/orders/SO-X/ship",
                 status=200, duration_ms=12, ip="127.0.0.1")

    result = audit.list_logs(db, actor="operator", limit=10)
    assert result["total"] >= 1
    first = result["items"][0]
    assert first["actor_kind"] == "operator"
    assert first["action"] == "POST /shop/admin/orders/*"
    assert first["status"] == 200
    assert first["trace_id"] == "t-audit-1"


def test_query_filters_by_status(db):
    audit.record(trace_id="t-audit-2", actor_kind="anonymous", actor="",
                 method="POST", path="/shop/orders", status=401, duration_ms=0)
    denied = audit.list_logs(db, status=401, limit=20)
    assert all(item["status"] == 401 for item in denied["items"])
    assert denied["total"] >= 1


# ------------------------------------------------------------------ 端到端
def test_order_create_is_audited_with_real_actor(client, db, monkeypatch):
    """中间件挂反了这里就会是 anonymous —— 这条用例守的就是顺序。"""
    from app import security

    monkeypatch.setattr(security, "settings", SimpleNamespace(
        service_token="svc-audit", operator_token="", jwt_secret="",
        auth_enforce="off", expose_docs=True, metrics_token=""))
    _reset_stock(db, 20)

    response = client.post("/shop/orders",
                           headers={"X-Service-Token": "svc-audit",
                                    "Idempotency-Key": "audit-e2e-1"},
                           json={"user_id": "u1001",
                                 "items": [{"sku_code": SKU, "quantity": 1}]})
    assert response.status_code == 200, response.text

    rows = _rows(db, "/shop/orders")
    assert rows, "下单必须留下审计记录"
    assert rows[0][0] == "service", "审计没拿到鉴权身份，说明中间件顺序错了"
    assert rows[0][1] == "customer-service-agent"
    assert rows[0][2] == "POST /shop/orders"
    assert rows[0][3] == 200


def test_audit_api_returns_rows(client):
    response = client.get("/shop/admin/audit", params={"limit": 5})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0
    assert "total" in payload["data"]
    assert isinstance(payload["data"]["items"], list)


# ------------------------------------------------------------------ 指标
def test_counter_and_histogram_format():
    metrics.reset()
    metrics.inc("x_total", {"a": "b"})
    metrics.observe("x_seconds", 0.03, {"path": "/shop/products"})
    text_body = metrics.render()

    assert "# TYPE x_total counter" in text_body
    assert 'x_total{a="b"} 1' in text_body
    # 桶是累积语义，observe 里已累加过，render 不能再加一遍
    assert 'x_seconds_bucket{le="0.05",path="/shop/products"} 1' in text_body
    assert 'x_seconds_bucket{le="0.005",path="/shop/products"} 0' in text_body
    assert 'x_seconds_bucket{le="+Inf",path="/shop/products"} 1' in text_body
    assert 'x_seconds_count{path="/shop/products"} 1' in text_body


def test_metrics_endpoint_counts_real_traffic(client):
    client.get("/shop/products?page_size=1")
    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds_bucket" in body
    # 请求结束在途数必须回到 0，否则说明有分支漏了减一
    assert "http_requests_in_flight 0" in body
    # /metrics 自己不参与统计，否则抓一次涨一次
    assert 'path="/metrics"' not in body
