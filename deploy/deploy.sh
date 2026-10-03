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

if [[ ! -f deploy/ecommerce.env ]]; then
  echo "缺少 deploy/ecommerce.env，请先执行： cp deploy/ecommerce.env.example deploy/ecommerce.env" >&2
  exit 1
fi

# ---------- 同步数据库密码到各 env 文件 ----------
# deploy/.env 是密码的唯一来源（POSTGRES_PASSWORD），
# 这里把它同步进 backend.env 与 ecommerce.env，避免改一个忘一个导致连不上库。
PG_PW="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE" | head -1)"
PG_USER="$(sed -n 's/^POSTGRES_USER=//p' "$ENV_FILE" | head -1)"
PG_USER="${PG_USER:-cs}"

if [[ -z "$PG_PW" ]]; then
  echo "在 $ENV_FILE 中找不到 POSTGRES_PASSWORD" >&2
  exit 1
fi

sync_url() {
  local file="$1" db="$2"
  if grep -q '^DATABASE_URL=' "$file"; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg2://${PG_USER}:${PG_PW}@postgres:5432/${db}|" "$file"
  else
    printf 'DATABASE_URL=postgresql+psycopg2://%s:%s@postgres:5432/%s\n' "$PG_USER" "$PG_PW" "$db" >> "$file"
  fi
}

# 客服 Agent 使用 asyncpg 驱动；中台使用 psycopg 驱动
sync_url_agent() {
  local file="$1" db="$2"
  if grep -q '^DATABASE_URL=' "$file"; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://${PG_USER}:${PG_PW}@postgres:5432/${db}|" "$file"
  else
    printf 'DATABASE_URL=postgresql+asyncpg://%s:%s@postgres:5432/%s\n' "$PG_USER" "$PG_PW" "$db" >> "$file"
  fi
}

sync_url_agent deploy/backend.env "${POSTGRES_DB:-customer_service}"
sync_url      deploy/ecommerce.env commerce
echo "==> 已同步数据库密码到 backend.env / ecommerce.env"

# ---------- 写入镜像 tag ----------
if grep -q '^IMAGE_TAG=' "$ENV_FILE"; then
  sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${TAG}|" "$ENV_FILE"
else
  printf '\nIMAGE_TAG=%s\n' "$TAG" >> "$ENV_FILE"
fi

# ---------- 选择编排文件 ----------
# 生产部署使用 docker-compose.prod.yml（只有 image:，纯拉取，不在服务器构建）。
# 服务器内存有限（2C2G），本地构建 Next.js 极易 OOM，因此 CI 路径必须走镜像。
COMPOSE_FILE="docker-compose.yml"
if [[ -f docker-compose.prod.yml ]]; then
  COMPOSE_FILE="docker-compose.prod.yml"
fi
echo "==> 使用编排文件: ${COMPOSE_FILE}"

dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# ---------- 拉取并重启 ----------
echo "==> 部署镜像 tag: ${TAG}"
if ! dc pull; then
  echo "" >&2
  echo "!! 拉取镜像失败。常见原因：" >&2
  echo "   1) GHCR 上的包是私有的 —— 在 GitHub Packages 页面把三个包设为 public，" >&2
  echo "      或执行 docker login ghcr.io -u <用户名> -p <read:packages 的 PAT>" >&2
  echo "   2) CI 尚未成功构建过镜像 —— 检查 Actions 里 build 三个 job 的状态" >&2
  exit 1
fi

# --remove-orphans 会清掉已从 compose 中移除的服务（例如原先的 MySQL）
dc up -d --remove-orphans

# ---------- 重新加载 Caddy 配置 ----------
# Caddyfile 是以 bind mount 挂进容器的：它的**内容**变了，compose 不会重建容器，
# 于是线上仍然跑着旧路由 —— 新加的反代规则（例如 /shop/* 转发到中台）会直接 404。
# 这里显式 reload；reload 依赖 admin API，失败就退回重启容器。
if docker ps --format '{{.Names}}' | grep -qx cs-caddy; then
  echo "==> 重新加载 Caddy 配置"
  if ! docker exec cs-caddy caddy reload --config /etc/caddy/Caddyfile; then
    echo "!! Caddy reload 失败（admin API 不可用？），改为重启容器"
    dc restart caddy
  fi
fi

# 清理历史镜像，防止磁盘被旧镜像撑满
docker image prune -f --filter "until=72h" >/dev/null 2>&1 || true

echo "==> 当前容器状态"
dc ps
