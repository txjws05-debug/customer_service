#!/bin/bash
# 【应急手段】构建「补丁镜像」：底座 = 上一次的镜像，只覆盖源码目录。
#
# 常态请用 deploy/build-full.sh（从源码完整构建）。
# 这条路径只在拿不到 python/uv 基础镜像时使用，代价是：
#   - 新增 Python 依赖不会生效（源码覆盖不到 .venv）；
#   - 镜像的「来源」仍是旧镜像，无法审计完整依赖树。
#
# 不需要网络：底座镜像已在本地，只做文件覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=${1:-$(date +%Y%m%d-%H%M)}
REGISTRY=${REGISTRY:-ghcr.io/txjws05-debug}

echo "== 构建 api:$TAG =="
docker build -q -f deploy/patch/api.Dockerfile -t "$REGISTRY/customer-service-api:$TAG" .

echo "== 构建 ecommerce:$TAG =="
# 用 ecommerce-service-backend 自身做上下文：仓库根的 .dockerignore 排除了该目录
docker build -q -f ecommerce-service-backend/Dockerfile.patch \
  -t "$REGISTRY/customer-service-ecommerce:$TAG" ecommerce-service-backend

echo "== 前端未改动，直接复用现有镜像打同标签 =="
BASE_WEB=$(docker inspect cs-frontend --format '{{.Config.Image}}')
docker tag "$BASE_WEB" "$REGISTRY/customer-service-web:$TAG"

echo "== 完成，可用标签：$TAG =="
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep "$TAG"
