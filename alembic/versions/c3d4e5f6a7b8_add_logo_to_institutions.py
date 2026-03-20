"""add logo columns to institutions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14
"""

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    # Columns may already exist if added manually — use IF NOT EXISTS to be safe
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS logo_bytes BYTEA")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS logo_content_type VARCHAR(50)")


def downgrade():
    op.drop_column("institutions", "logo_content_type")
    op.drop_column("institutions", "logo_bytes")
