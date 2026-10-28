"""baseline：把改造前的既有结构标记为起点

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-28

既有库是 `create_all` + `ensure_columns` 建出来的，没有迁移历史。
这里不改结构，只用 `alembic stamp 0001_baseline` 打上标记，
之后的结构变更一律通过新迁移文件完成。
"""

from __future__ import annotations

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
