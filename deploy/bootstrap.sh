#!/usr/bin/env bash
# ============================================================
# 首次部署引导（只需在服务器上执行一次）
#
# 作用：
#   1. 从模板生成 deploy/.env、deploy/backend.env、deploy/ecommerce.env
#   2. 若 deploy/.env 里还是占位密码，则自动生成随机强密码
#   3. 把数据库密码与 JWT 密钥同步进各运行时 env 文件
#
# 用法：
#   bash deploy/bootstrap.sh
# 然后编辑 deploy/backend.env 填入真实 LLM_API_KEY，再执行：
#   docker compose --env-file deploy/.env up -d --build
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="deploy/.env"
PLACEHOLDER="please_change_this_pg_password"

echo "==> 1/4 从模板生成配置文件"
[[ -f "$ENV_FILE" ]]          || cp deploy/.env.example "$ENV_FILE"
[[ -f deploy/backend.env ]]   || cp deploy/backend.env.example deploy/backend.env
[[ -f deploy/ecommerce.env ]] || cp deploy/ecommerce.env.example deploy/ecommerce.env

echo "==> 2/4 检查数据库密码"
CUR_PW="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE" | head -1)"
if [[ -z "$CUR_PW" || "$CUR_PW" == "$PLACEHOLDER" ]]; then
  NEW_PW="$(openssl rand -hex 16)"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${NEW_PW}|" "$ENV_FILE"
  echo "    已生成随机 POSTGRES_PASSWORD"
else
  echo "    沿用 deploy/.env 中已有的 POSTGRES_PASSWORD"
fi

PG_PW="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE" | head -1)"
PG_USER="$(sed -n 's/^POSTGRES_USER=//p' "$ENV_FILE" | head -1)"
PG_DB="$(sed -n 's/^POSTGRES_DB=//p' "$ENV_FILE" | head -1)"
PG_USER="${PG_USER:-cs}"
PG_DB="${PG_DB:-customer_service}"

echo "==> 3/4 同步数据库连接串（避免手工改漏）"
set_url() {
  local file="$1" driver="$2" db="$3"
  local url="postgresql+${driver}://${PG_USER}:${PG_PW}@postgres:5432/${db}"
  if grep -q '^DATABASE_URL=' "$file"; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${url}|" "$file"
  else
    printf 'DATABASE_URL=%s\n' "$url" >> "$file"
  fi
  echo "    $file -> ${db}"
}
set_url deploy/backend.env   asyncpg  "$PG_DB"    # 客服 Agent
set_url deploy/ecommerce.env psycopg2 commerce    # 电商中台

echo "==> 4/4 检查 JWT 密钥"
if grep -qE '^JWT_SECRET_KEY=(replace_with_a_long_random_string)?$' deploy/backend.env; then
  JWT="$(openssl rand -hex 32)"
  sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWT}|" deploy/backend.env
  echo "    已生成随机 JWT_SECRET_KEY"
else
  echo "    沿用已有的 JWT_SECRET_KEY"
fi

if grep -q '^LLM_API_KEY=sk-replace-with-your-own-key$' deploy/backend.env; then
  echo ""
  echo "!! 还需要手动一步：编辑 deploy/backend.env 填入真实 LLM_API_KEY"
  echo "   nano deploy/backend.env"
  echo ""
fi

echo "==> 引导完成，可以执行："
echo "   docker compose --env-file deploy/.env up -d --build"
