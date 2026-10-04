"""反代 API 前缀 与 前端页面路由 不能撞车。

踩过的坑：Caddy 里 `@shop path /shop/*` 把 `/shop/*` 全部转发给电商中台，
而前端商品详情页恰好也是 `/shop/[productId]`。结果点商品卡片时浏览器请求
`/shop/SKU10005`，被当成接口发给中台，中台只认 `/shop/products/{id}`，
于是页面直接显示 `{"detail":"Not Found"}` —— 列表页（`/shop`，没有斜杠，
不匹配 `/shop/*`）却是好的，非常有迷惑性。

修法是把页面路由挪到 `/mall/*`，API 留在 `/shop/*`。这个测试守住这条边界：
**任何一个反代 API 前缀，都不能有同名的前端页面路由**。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
APP_DIR = ROOT / "frontend" / "src" / "app"


def _api_prefixes() -> set[str]:
    """从 Caddyfile 的具名 matcher 里取出被反代的第一段路径。"""
    text = CADDYFILE.read_text(encoding="utf-8")
    prefixes: set[str] = set()
    # 形如：  @api path /api/* /docs /docs/*
    for match in re.finditer(r"@(\w+)\s+path\s+([^\n{]+)", text):
        for token in match.group(2).split():
            if not token.startswith("/"):
                continue
            segment = token.strip().split("/")[1] if "/" in token.strip()[1:] else token.strip("/")
            if segment:
                prefixes.add(segment)
    return prefixes


def _page_routes() -> set[str]:
    """前端各页面的第一段路径：app/(app)/mall/page.tsx → mall。"""
    routes: set[str] = set()
    for page in APP_DIR.rglob("page.tsx"):
        relative = page.relative_to(APP_DIR)
        parts = [part for part in relative.parts
                 if not (part.startswith("(") and part.endswith(")")) and part != "page.tsx"]
        if not parts:
            continue  # 根路径
        first = parts[0]
        if first.startswith("[") or first.startswith("@"):
            continue  # 动态段/插槽不算固定前缀
        routes.add(first)
    return routes


def test_caddy_api_prefixes_do_not_shadow_frontend_pages():
    api = _api_prefixes()
    pages = _page_routes()

    assert "api" in api and "shop" in api, f"没解析出预期的 API 前缀：{api}"
    assert pages, "没解析出任何页面路由，解析逻辑可能失效了"

    collisions = sorted(api & pages)
    assert not collisions, (
        f"这些反代前缀与前端页面同名，页面会被当成接口：{collisions}。"
        "API 命名空间和页面路由必须分开（例如页面用 /mall，接口用 /shop）。")


def test_product_links_point_at_the_page_namespace_not_the_api():
    """页面里的商品链接必须指向页面命名空间，否则点了就是 JSON 报错。"""
    pages = _page_routes()
    api = _api_prefixes()

    bad: list[str] = []
    pattern = re.compile(r"href=\{?[`\"']/([a-z0-9-]+)")
    for source in (ROOT / "frontend" / "src").rglob("*.tsx"):
        for line_number, line in enumerate(
                source.read_text(encoding="utf-8").splitlines(), start=1):
            for segment in pattern.findall(line):
                if segment in api and segment not in pages:
                    bad.append(f"{source.name}:{line_number} / {segment}")

    assert not bad, f"页面链接指向了接口命名空间：{bad}"
