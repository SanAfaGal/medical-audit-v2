"""add admission column to invoices

Revision ID: e1f2a3b4c5d6
Revises: a7f3b1e2c8d5
Create Date: 2026-03-16
"""

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "a7f3b1e2c8d5"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS admission VARCHAR(50)")


def downgrade():
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS admission")
