"""知识库管理页与接口守卫。

页面是后端直接吐的 HTML（前端镜像重建需要 npm，这台机器连不上），
所以这里至少保证：页面结构完整、没有令牌时接口一定是拒绝的。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ws.api import handoff_router, kb_router


def test_ui_html_has_required_controls():
    html = kb_router.KB_UI_HTML
    for marker in ('id="token"', 'id="rows"', 'id="q"', "重建索引", "/api/kb/chunks"):
        assert marker in html, marker


def test_ui_html_warns_about_temporary_delete():
    """删除是临时的（重建会回来），页面必须明说，否则运营会误判。"""
    assert "临时下线" in kb_router.KB_UI_HTML
    assert "重建后会恢复" in kb_router.KB_UI_HTML


def test_operator_guard_rejects_when_token_not_configured(monkeypatch):
    monkeypatch.setattr(handoff_router, "settings",
                        SimpleNamespace(operator_token=""))
    with pytest.raises(HTTPException) as exc:
        handoff_router.require_operator(x_operator_token="whatever")
    assert exc.value.status_code == 403


def test_operator_guard_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(handoff_router, "settings",
                        SimpleNamespace(operator_token="right"))
    with pytest.raises(HTTPException) as exc:
        handoff_router.require_operator(x_operator_token="wrong")
    assert exc.value.status_code == 403


def test_operator_guard_accepts_matching_token(monkeypatch):
    monkeypatch.setattr(handoff_router, "settings",
                        SimpleNamespace(operator_token="right"))
    assert handoff_router.require_operator(x_operator_token="right") == "operator"
