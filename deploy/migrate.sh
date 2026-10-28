#!/bin/bash
# 数据库迁移入口：migrate.sh [alembic 参数]
#
#   bash deploy/migrate.sh                  # 默认 upgrade head
#   bash deploy/migrate.sh "downgrade -1"   # 回退一步
#   bash deploy/migrate.sh current          # 查看当前版本
#   bash deploy/migrate.sh history          # 查看迁移历史
#
# 为什么不放在应用启动时：
# - 迁移失败必须「停下来」，不能像 create_all 那样静默继续启动；
# - 多副本时启动即迁移会并发抢 DDL 锁；
# - 这台机器访问不了 PyPI，所以 alembic 用离线 wheel 装进一次性容器，
#   不污染线上镜像（正式 CI 构建时 alembic 已在依赖里）。
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
WHEELS=${WHEELS:-/opt/wheels}
CMD=${1:-"upgrade head"}

TAG=$(sed -n 's/^IMAGE_TAG=//p' "$APP_DIR/deploy/.env" | head -1)
IMAGE=${IMAGE:-ghcr.io/txjws05-debug/customer-service-ecommerce:${TAG}}

# 连接串只从 env 文件读，不回显（里面有密码）
DB_URL=$(sed -n 's/^DATABASE_URL=//p' "$APP_DIR/deploy/ecommerce.env" | head -1)
[ -n "$DB_URL" ] || { echo "deploy/ecommerce.env 里没有 DATABASE_URL" >&2; exit 1; }

echo "== 镜像 $IMAGE ｜ 执行：alembic $CMD =="
docker run --rm \
  --network container:cs-ecommerce \
  -v "$APP_DIR:/src" -v "$WHEELS:/wheels" \
  -w /src/ecommerce-service-backend \
  -e DATABASE_URL="$DB_URL" \
  --entrypoint /bin/sh "$IMAGE" -c "
set -e
pip install -q --no-index --find-links=/wheels \
  --target=/app/.venv/lib/python3.12/site-packages alembic Mako MarkupSafe 2>&1 | grep -v 'already exists' || true
/app/.venv/bin/python -m alembic $CMD
"
