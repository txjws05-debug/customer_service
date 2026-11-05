"""product_skus.stock >= 0

Revision ID: 0006_stock_nonneg
Revises: 0005_refunds
Create Date: 2026-11-05

立即购买时同一 SKU 多行会绕过逐行库存校验、把库存扣成负数。代码已修（先合并），
这里在库表上再兜一层。约束已存在时跳过（空库升级走 create_all 时已建好）。
"""

from __future__ import annotations

from alembic import op

revision = "0006_stock_nonneg"
down_revision = "0005_refunds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conname = 'ck_product_skus_stock_nonneg') THEN
                ALTER TABLE product_skus
                    ADD CONSTRAINT ck_product_skus_stock_nonneg CHECK (stock >= 0);
            END IF;
        END $$;
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE product_skus DROP CONSTRAINT IF EXISTS ck_product_skus_stock_nonneg")
