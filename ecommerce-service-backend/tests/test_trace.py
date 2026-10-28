"""trace_id 贯穿：响应头要带，且要复用调用方传来的 id。"""

from __future__ import annotations


def test_response_carries_trace_id(client):
    response = client.get("/shop/products?page_size=1")
    assert response.status_code == 200
    trace_id = response.headers.get("X-Request-Id")
    assert trace_id and len(trace_id) >= 8


def test_incoming_trace_id_is_reused(client):
    """上游（客服 Agent）传来的 id 必须原样延续，否则两个服务的日志串不起来。"""
    response = client.get("/shop/products?page_size=1",
                          headers={"X-Request-Id": "trace-from-agent"})
    assert response.headers.get("X-Request-Id") == "trace-from-agent"


def test_trace_id_present_even_on_rejection(client):
    """被鉴权拒掉的请求也要有 id —— 故障排查往往正是从失败请求开始。"""
    response = client.get("/shop/users/u1001/cart")  # AUTH_ENFORCE 默认 off，带 id 即可
    assert response.headers.get("X-Request-Id")
