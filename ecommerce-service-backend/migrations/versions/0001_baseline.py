"""baseline：建出改造前的既有结构

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-28

原先是空操作，只给既有库打版本号 —— 那样空库跑 `upgrade head` 会失败：
0002 要在 orders 上建索引，可表根本不存在，建表靠的还是应用启动时的
create_all，等于迁移链只对「已经有表的库」成立。

现在这一步用 ORM metadata 建出全表：空库能一路升到 head，
已有库因为 checkfirst=True 也不会被改动。
"""
from __future__ import annotations

from alembic import op
from app.models import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # downgrade base 等于「把这个库清空」。只在演练/临时库上使用，
    # 线上库执行前必须确认备份可用。
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
