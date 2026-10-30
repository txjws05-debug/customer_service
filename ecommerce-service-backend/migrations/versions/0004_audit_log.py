"""audit_log：操作审计

Revision ID: 0004_audit_log
Revises: 0003_idempotency
Create Date: 2026-10-30

同样用 IF NOT EXISTS：0001_baseline 走 create_all，空库升级时表已建好。
（这条约束写在 0003 的注释里，此处遵守。）
"""

from __future__ import annotations

from alembic import op

revision = "0004_audit_log"
down_revision = "0003_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id           BIGSERIAL PRIMARY KEY,
            trace_id     VARCHAR(32),
            actor_kind   VARCHAR(16)  NOT NULL,
            actor        VARCHAR(64)  NOT NULL,
            method       VARCHAR(8)   NOT NULL,
            path         VARCHAR(255) NOT NULL,
            action       VARCHAR(64)  NOT NULL,
            status       INTEGER      NOT NULL,
            duration_ms  INTEGER      NOT NULL,
            ip           VARCHAR(64),
            created_at   TIMESTAMP    NOT NULL
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_created_at "
               "ON audit_log (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_actor_created "
               "ON audit_log (actor, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_action_created "
               "ON audit_log (action, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
