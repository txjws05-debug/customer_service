"""orders(user_id, created_at) 联合索引：我的订单列表的支撑索引

Revision ID: 0002_orders_user_created
Revises: 0001_baseline
Create Date: 2026-10-28

「我的订单」按 user_id 过滤、按 created_at 倒序分页，之前只有 user_id 单列外键，
数据量上来会退化成排序 + 全表过滤。先补上这条复合索引。
用 IF NOT EXISTS 写，重复执行不会报错（多人环境里这很重要）。
"""

from __future__ import annotations

from alembic import op

revision = "0002_orders_user_created"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_user_created "
        "ON orders (user_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_user_created")
