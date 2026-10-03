#!/usr/bin/env bash
# ============================================================
# deploy/detect-changes.sh 的行为测试。
#
# 它决定「这次要重建哪几个镜像」，判错的代价很具体：
#   · 漏判 → 改了的代码没进镜像，部署上去还是旧的（最危险）
#   · 多判 → 白白多构建 + 多拉一个镜像（回到慢的路上）
# 所以每个组件的代表路径都要有断言。
#
# 用法：bash tests/test_detect_changes.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

fail() { echo "FAIL: $1" >&2; exit 1; }

# run <文件列表（换行分隔）> → 打印 detect-changes.sh 的输出
run() {
  printf '%s\n' "$1" | bash deploy/detect-changes.sh
}

echo "1) 只改前端：只重建 web"
out="$(run 'frontend/src/app/(app)/cart/page.tsx')"
echo "$out" | grep -q '^api=false$' || fail "改前端不该重建 api"
echo "$out" | grep -q '^web=true$' || fail "改前端必须重建 web"
echo "$out" | grep -q '^images_csv=,web,$' || fail "images_csv 应为 ,web,"
echo "$out" | grep -q '^deploy_needed=true$' || fail "有代码改动就必须部署"
echo "   OK"

echo "2) 只改后端：只重建 api"
out="$(run 'ws/task/custom/shop_cart.py')"
echo "$out" | grep -q '^api=true$' || fail "改 ws/ 必须重建 api"
echo "$out" | grep -q '^images_csv=,api,$' || fail "images_csv 应为 ,api,"
echo "   OK"

echo "3) 依赖清单变了也要重建 api（uv.lock / pyproject / Dockerfile）"
for f in "uv.lock" "pyproject.toml" "Dockerfile"; do
  run "$f" | grep -q '^api=true$' || fail "$f 变化必须重建 api"
done
echo "   OK"

echo "4) 改中台：只重建 ecommerce"
out="$(run 'ecommerce-service-backend/app/shop_service.py')"
echo "$out" | grep -q '^ecommerce=true$' || fail "改中台必须重建 ecommerce"
echo "$out" | grep -q '^api=false$' || fail "改中台不该重建 api"
echo "   OK"

echo "5) 三个组件都改：三个都重建"
out="$(run 'ws/api/app.py
frontend/src/lib/shop.ts
ecommerce-service-backend/app/models.py')"
for key in api ecommerce web; do
  echo "$out" | grep -q "^${key}=true$" || fail "$key 应被判定为有改动"
done
echo "$out" | grep -q '^images_csv=,api,ecommerce,web,$' || fail "images_csv 应含三个组件"
echo "   OK"

echo "6) 只改部署配置：不重建镜像，但仍要部署"
out="$(run 'deploy/Caddyfile')"
echo "$out" | grep -q '^images_csv=,$' || fail "只改部署配置时不应重建任何镜像"
echo "$out" | grep -q '^deploy_needed=true$' || fail "部署配置变化必须触发部署"
echo "   OK"

echo "7) 只改文档：什么都不做"
out="$(run 'README.md')"
echo "$out" | grep -q '^deploy_needed=false$' || fail "文档改动不该触发部署"
echo "$out" | grep -q '^images_csv=,$' || fail "文档改动不该重建镜像"
echo "   OK"

echo "8) 空输入（没有可比对的 diff）：什么都不做"
out="$(printf '' | bash deploy/detect-changes.sh)"
echo "$out" | grep -q '^deploy_needed=false$' || fail "空输入不该触发部署"
echo "   OK"

echo "9) 组件名不会互相误匹配（api 与 ecommerce 前缀分别判断）"
out="$(run 'ecommerce-service-backend/README.md')"
echo "$out" | grep -q '^api=false$' || fail "ecommerce 的改动被误判成 api"
echo "   OK"

echo
echo "detect-changes.sh 全部断言通过"
