#!/usr/bin/env python3
"""生成商品封面占位图（SVG）到 frontend/public/products/。

为什么是「自己生成」而不是找真实商品图：

- 外部图床/电商站点的图会热链失效，也可能有版权问题；种子数据里原来的
  https://example.com/images/*.jpg 就是这么来的 —— 浏览器只会显示碎图；
- 生成结果提交进仓库，随前端镜像一起发布（Dockerfile 会 COPY public），
  部署即可见。**不需要往服务器手工塞文件**：手工放的文件下次重建容器就没了，
  而且和部署流程互相打架；
- 图上直接写商品名 + 品牌 + 类目，缩略图也能看出是哪个商品。

商品清单与类目不写死在这里，而是从后端种子文件解析出来，保证图片和商品
不会对不上（改了商品重跑本脚本即可）。

用法：python scripts/gen_product_covers.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
INIT_DATA = ROOT / "ecommerce-service-backend" / "app" / "init_data.py"
SEED_SHOP = ROOT / "ecommerce-service-backend" / "app" / "seed_shop.py"
OUT_DIR = ROOT / "frontend" / "public" / "products"

# 按类目配色：(背景浅色, 装饰色, 文字色)
PALETTE: dict[str, tuple[str, str, str]] = {
    "手机数码": ("#eef2ff", "#c7d2fe", "#312e81"),
    "智能穿戴": ("#e0f2fe", "#bae6fd", "#0c4a6e"),
    "厨房家电": ("#fef3c7", "#fde68a", "#78350f"),
    "日用百货": ("#ffe4e6", "#fecdd3", "#881337"),
    "电脑办公": ("#d1fae5", "#a7f3d0", "#064e3b"),
}
FALLBACK_PALETTE = ("#f1f5f9", "#e2e8f0", "#1e293b")

FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans CJK SC, sans-serif"

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{light}"/>
      <stop offset="1" stop-color="{light}"/>
      <stop offset="1" stop-color="{deco}"/>
    </linearGradient>
  </defs>
  <rect width="800" height="800" fill="{light}"/>
  <circle cx="400" cy="330" r="220" fill="{deco}" opacity="0.35"/>
{name_lines}
  <text x="400" y="{meta_y}" text-anchor="middle" font-family="{font}" font-size="30" fill="{ink}" opacity="0.75">{meta}</text>
</svg>
"""


def _load_products() -> list[tuple[str, str, str, str]]:
    """返回 [(product_id, title, category, brand)]，顺序与种子一致。"""
    init_text = INIT_DATA.read_text(encoding="utf-8")
    seed_text = SEED_SHOP.read_text(encoding="utf-8")

    # init_data.py: product_id="SKU10001",  title="iPhone 15 Pro 256G 远峰蓝"
    products = re.findall(
        r'product_id="(SKU\d+)"\s*,\s*title="([^"]+)"', init_text)
    # seed_shop.py: "SKU10001": ("手机数码", "Apple"),
    meta = {
        pid: (category, brand)
        for pid, category, brand in re.findall(
            r'"(SKU\d+)": \("([^"]+)", "([^"]+)"\)', seed_text)
    }

    if not products:
        sys.exit("没能从 init_data.py 解析出商品，请检查文件格式是否变了")

    return [
        (pid, title, *meta.get(pid, ("", "")))
        for pid, title in products
    ]


def _wrap(text: str, max_chars: int = 14) -> list[str]:
    """按空格优先断行，长串再硬切 —— 商品名要在 800px 宽里放得下。"""
    lines: list[str] = []
    current = ""
    for token in text.split(" "):
        piece = token if not current else f"{current} {token}"
        if len(piece) <= max_chars:
            current = piece
            continue
        if current:
            lines.append(current)
        while len(token) > max_chars:
            lines.append(token[:max_chars])
            token = token[max_chars:]
        current = token
    if current:
        lines.append(current)
    return lines


def _render(title: str, category: str, brand: str) -> str:
    light, deco, ink = PALETTE.get(category, FALLBACK_PALETTE)

    # 换行不能丢内容：先按 14 字断，行数超过 3 就放宽到 18 / 22，
    # 实在放不下才把尾巴并进最后一行（宁可挤一点，也不能把商品名吞掉）
    lines: list[str] = []
    for max_chars in (14, 18, 22):
        lines = _wrap(title, max_chars)
        if len(lines) <= 3:
            break
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = title[-max_chars:]

    font_size = {1: 62, 2: 54}.get(len(lines), 46)
    step = font_size + 10
    start_y = 330 if len(lines) <= 2 else 300
    name_lines = "\n".join(
        f'  <text x="400" y="{start_y + index * step}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{font_size}" font-weight="700" fill="{ink}">'
        f"{_escape(line)}</text>"
        for index, line in enumerate(lines)
    )
    meta_y = start_y + len(lines) * step + 36
    meta = " · ".join(part for part in (brand, category) if part)

    return SVG_TEMPLATE.format(
        label=_escape(title), light=light, deco=deco, ink=ink,
        name_lines=name_lines, meta=_escape(meta), meta_y=meta_y, font=FONT,
    )


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    products = _load_products()
    # 兜底图：万一将来加了商品却忘了生成，前端也不至于出现碎图
    (OUT_DIR / "default.svg").write_text(_render("商品图片", "", ""), encoding="utf-8")

    for product_id, title, category, brand in products:
        path = OUT_DIR / f"{product_id}.svg"
        path.write_text(_render(title, category, brand), encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ← {title}")

    print(f"已生成 {len(products)} 张商品占位图 + 1 张兜底图 → {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
