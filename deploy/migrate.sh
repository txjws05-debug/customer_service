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
# - 多副本时启动即迁移会并发抢 DDL 锁。
#
# alembic 在镜像的依赖里（2026-10-30 起完整构建自带 1.20.1），
# 不再需要从 /opt/wheels 离线安装 —— 那段临时方案随完整镜像退役。
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
CMD=${1:-"upgrade head"}

TAG=$(sed -n 's/^IMAGE_TAG=//p' "$APP_DIR/deploy/.env" | head -1)
IMAGE=${IMAGE:-ghcr.io/txjws05-debug/customer-service-ecommerce:${TAG}}

# 连接串只从 env 文件读，不回显（里面有密码）
DB_URL=$(sed -n 's/^DATABASE_URL=//p' "$APP_DIR/deploy/ecommerce.env" | head -1)
[ -n "$DB_URL" ] || { echo "deploy/ecommerce.env 里没有 DATABASE_URL" >&2; exit 1; }

echo "== 镜像 $IMAGE ｜ 执行：alembic $CMD =="
docker run --rm \
  --network container:cs-ecommerce \
  -v "$APP_DIR:/src" \
  -w /src/ecommerce-service-backend \
  -e DATABASE_URL="$DB_URL" \
  --entrypoint /app/.venv/bin/python "$IMAGE" -m alembic $CMD
