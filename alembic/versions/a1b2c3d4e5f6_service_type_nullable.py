"""make services.service_type_id nullable

Revision ID: a1b2c3d4e5f6
Revises: 3c5f8a2d1e04
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "3c5f8a2d1e04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "services",
        "service_type_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Set any NULLs to a fallback before restoring NOT NULL
    op.execute(
        "UPDATE services SET service_type_id = (SELECT id FROM service_types WHERE code = 'GENERAL' LIMIT 1) "
        "WHERE service_type_id IS NULL"
    )
    op.alter_column(
        "services",
        "service_type_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
