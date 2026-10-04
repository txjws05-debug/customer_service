#!/usr/bin/env bash
# ============================================================
# 商品封面占位图的完整性检查。
#
# 背景：种子里原本是 https://example.com/images/*.jpg 这种假地址，
# 页面上全是碎图（浏览器只能显示破图图标）。现在封面改成随前端一起发布的
# /products/<id>.svg，因此必须保证「后端引用的每一张图都真的存在」，
# 否则又会悄悄退回碎图 —— 这类问题在浏览器里才发现，代价很高。
#
# 用法：bash tests/test_product_covers.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

# 本地（Windows Git bash）用 python，CI（ubuntu）用 python3
PY="${PYTHON:-python3}"

IDS="$(grep -oE '"SKU[0-9]+"' ecommerce-service-backend/app/seed_shop.py | tr -d '"' | sort -u)"
COUNT="$(printf '%s\n' "$IDS" | grep -c .)"
[ "$COUNT" -gt 0 ] || { echo "FAIL: 没能从种子文件解析出商品 id"; exit 1; }

fail=0

echo "1) 每个商品都要有对应的封面文件"
for id in $IDS; do
  file="frontend/public/products/${id}.svg"
  if [ ! -f "$file" ]; then
    echo "   FAIL: 缺少 $file（页面上会显示碎图）"
    fail=1
  fi
done
[ "$fail" -eq 0 ] && echo "   OK（$COUNT 个）"

echo "2) 后端引用的封面必须是本地路径，不能是 example.com 假地址"
# 注意只匹配「赋值」形态：注释里提到 example.com 是允许的（说明历史原因）
grep -q 'cover_url="/products/' ecommerce-service-backend/app/init_data.py \
  || { echo "   FAIL: 种子里没有把 cover_url 指向 /products/<id>.svg"; fail=1; }
if grep -q 'cover_url="https://example.com' \
     ecommerce-service-backend/app/init_data.py \
     ecommerce-service-backend/app/seed_shop.py; then
  echo "   FAIL: 种子仍在写 example.com 假图地址（浏览器会显示碎图）"
  fail=1
fi
# 回填逻辑：老库里已经写进去的假地址也要能自动修掉
grep -q 'f"/products/{product.product_id}.svg"' ecommerce-service-backend/app/seed_shop.py \
  || { echo "   FAIL: 种子里缺少封面回填逻辑（老库不会被修好）"; fail=1; }
[ "$fail" -eq 0 ] && echo "   OK"

echo "3) SVG 必须是合法 XML，并且图上真的写了商品名（不是空白图）"
"$PY" - "$IDS" <<'PY' || fail=1
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ns = "{http://www.w3.org/2000/svg}"
ids = sys.argv[1].split()
init_text = pathlib.Path(
    "ecommerce-service-backend/app/init_data.py").read_text(encoding="utf-8")
title_by_id = dict(re.findall(
    r'product_id="(SKU\d+)"\s*,\s*title="([^"]+)"', init_text))

bad = []
for pid in ids:
    path = pathlib.Path("frontend/public/products") / f"{pid}.svg"
    if not path.exists():
        bad.append(f"{pid}: 文件不存在")
        continue
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        bad.append(f"{pid}: SVG 不是合法 XML（{exc}）")
        continue
    text = "".join(node.text or "" for node in root.iter(ns + "text"))
    # 长商品名会被断行，按空格拆开逐段检查
    missing = [part for part in title_by_id.get(pid, "").split(" ") if part not in text]
    if missing:
        bad.append(f"{pid}: 图上缺少商品名片段 {missing}")

if bad:
    print("   FAIL: " + "; ".join(bad))
    sys.exit(1)
print(f"   OK（{len(ids)} 张 SVG 合法且含商品名）")
PY

[ "$fail" -eq 0 ] || exit 1
echo
echo "商品封面检查通过"
