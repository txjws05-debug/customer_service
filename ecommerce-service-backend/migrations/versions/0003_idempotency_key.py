"""idempotency_key：请求级幂等记录

Revision ID: 0003_idempotency
Revises: 0002_orders_user_created
Create Date: 2026-10-29

为什么用原生 SQL 而不是 op.create_table：0001_baseline 走的是
`Base.metadata.create_all`，空库升级到 0001 时这张表就已经被建出来了，
再 op.create_table 会直接报「表已存在」。写成 IF NOT EXISTS，
让「空库一条链升上来」和「存量库增量升级」两种入口都成立。

反过来说，这也是 0001 用 create_all 的代价：后续每个迁移都得自己保证幂等。
真正干净的做法是 0001 里逐表写 CREATE TABLE —— 那是把既有结构抄一遍、
两千多行且容易抄错，权衡后保留现状，但约束必须写在这里：
**新增迁移一律 IF NOT EXISTS，不允许假设表不存在。**
"""

from __future__ import annotations

from alembic import op

revision = "0003_idempotency"
down_revision = "0002_orders_user_created"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_key (
            id           BIGSERIAL PRIMARY KEY,
            scope        VARCHAR(32)  NOT NULL,
            key          VARCHAR(64)  NOT NULL,
            status       VARCHAR(16)  NOT NULL,
            result_ref   VARCHAR(64),
            reason       VARCHAR(200),
            attempts     INTEGER      NOT NULL DEFAULT 1,
            lease_until  TIMESTAMP,
            created_at   TIMESTAMP    NOT NULL,
            updated_at   TIMESTAMP    NOT NULL
        )
        """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_idempotency_scope_key "
        "ON idempotency_key (scope, key)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_key")
