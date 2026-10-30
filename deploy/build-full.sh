#!/bin/bash
# 完整构建：从源码重建镜像，不依赖任何旧镜像。
#
# 这是常态路径。`build-local.sh`（补丁镜像）只在网络不可用时当应急手段 ——
# 它的底座是「上一次的镜像」，一旦新增依赖就无法生效（源码覆盖不到 venv）。
#
#   bash deploy/build-full.sh              # tag 默认日期时间
#   bash deploy/build-full.sh 20261101-x
#
# 依赖网络：python:3.12-slim、ghcr.io/astral-sh/uv（首次约需拉取一次）。
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=${1:-$(date +%Y%m%d-%H%M)}
REGISTRY=${REGISTRY:-ghcr.io/txjws05-debug}

echo "== api（Agent）=="
docker build -q -t "$REGISTRY/customer-service-api:$TAG" -f Dockerfile .

echo "== ecommerce（中台）=="
docker build -q -t "$REGISTRY/customer-service-ecommerce:$TAG" \
  -f ecommerce-service-backend/Dockerfile ecommerce-service-backend

# 前端：Next.js `npm run build` 在 2C2G 上容易 OOM，默认不重建。
# 显式传 REBUILD_WEB=1 才做，并且要挑服务空闲时段。
if [ "${REBUILD_WEB:-0}" = "1" ]; then
  echo "== web（显式重建）=="
  docker build -q -t "$REGISTRY/customer-service-web:$TAG" frontend
else
  echo "== web 跳过（前端源码未变；要重建加 REBUILD_WEB=1）=="
  BASE_WEB=$(docker inspect cs-frontend --format '{{.Config.Image}}')
  docker tag "$BASE_WEB" "$REGISTRY/customer-service-web:$TAG"
fi

echo "== 完成 =="
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep "$TAG"
