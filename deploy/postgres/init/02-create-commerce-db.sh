#!/bin/bash
# ============================================================
# 首次初始化 PostgreSQL 时自动执行（仅当数据卷为空时运行一次）。
#
# 作用：为电商中台创建独立的 commerce 库，归 POSTGRES_USER 所有。
#   - customer_service 库由容器的 POSTGRES_DB 自动创建，供客服 Agent 使用
#   - commerce 库供电商中台使用
# 两个库共用一个 PostgreSQL 实例，省内存且便于分别备份。
# ============================================================
set -e

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE commerce OWNER $POSTGRES_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'commerce')\gexec
EOSQL

echo "[init] commerce 库已就绪 (owner=$POSTGRES_USER)"
