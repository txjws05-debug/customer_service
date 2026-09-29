#!/usr/bin/env bash
# ============================================================
# 服务器端拉取并重启服务
# 由 GitHub Actions 通过 SSH 调用：IMAGE_TAG=<commit-sha> bash deploy/deploy.sh
#
# 前置条件（只需做一次）：
#   docker login ghcr.io -u <你的GitHub用户名> -p <只含 read:packages 的PAT>
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

TAG="${IMAGE_TAG:-latest}"
ENV_FILE="deploy/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少 $ENV_FILE，请先执行： cp deploy/.env.example deploy/.env 并填写密码" >&2
  exit 1
fi

if [[ ! -f deploy/backend.env ]]; then
  echo "缺少 deploy/backend.env，请先执行： cp deploy/backend.env.example deploy/backend.env 并填写 LLM Key / JWT 密钥" >&2
  exit 1
fi

# 把本次要部署的镜像 tag 写入 .env（覆盖旧值，保留其余配置）
if grep -q '^IMAGE_TAG=' "$ENV_FILE"; then
  sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${TAG}|" "$ENV_FILE"
else
  printf '\nIMAGE_TAG=%s\n' "$TAG" >> "$ENV_FILE"
fi

echo "==> 部署镜像 tag: ${TAG}"
docker compose --env-file "$ENV_FILE" pull
docker compose --env-file "$ENV_FILE" up -d --remove-orphans

# 清理历史镜像，防止磁盘被旧镜像撑满
docker image prune -f --filter "until=72h" >/dev/null 2>&1 || true

echo "==> 当前容器状态"
docker compose --env-file "$ENV_FILE" ps
