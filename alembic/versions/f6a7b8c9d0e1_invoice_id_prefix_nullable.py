"""make invoice_id_prefix nullable — some institutions don't use a prefix

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "institutions",
        "invoice_id_prefix",
        existing_type=sa.String(20),
        nullable=True,
    )


def downgrade():
    # Set empty strings to empty (can't restore original NOT NULL constraint
    # if any rows have NULL, so just revert the constraint)
    op.execute("UPDATE institutions SET invoice_id_prefix = '' WHERE invoice_id_prefix IS NULL")
    op.alter_column(
        "institutions",
        "invoice_id_prefix",
        existing_type=sa.String(20),
        nullable=False,
    )
