"""refunds：退款流水

Revision ID: 0005_refunds
Revises: 0004_audit_log
Create Date: 2026-11-05

此前取消已付款订单、完成售后都不记退款，线上出现「已取消、已付款、无退款记录」
的订单。同样用 IF NOT EXISTS（0001_baseline 走 create_all，空库升级时表已建好）。
"""

from __future__ import annotations

from alembic import op

revision = "0005_refunds"
down_revision = "0004_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id          SERIAL PRIMARY KEY,
            refund_no   VARCHAR(64)   NOT NULL UNIQUE,
            order_id    INTEGER       NOT NULL REFERENCES orders(id),
            payment_id  INTEGER       NOT NULL REFERENCES payments(id),
            amount      NUMERIC(10,2) NOT NULL,
            source      VARCHAR(16)   NOT NULL,
            ticket_no   VARCHAR(64),
            reason      VARCHAR(255)  NOT NULL,
            created_at  TIMESTAMP     NOT NULL
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_refunds_order_id ON refunds (order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_refunds_payment_id ON refunds (payment_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refunds")
