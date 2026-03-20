"""make invoices.service_type_id nullable

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "invoices",
        "service_type_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE invoices SET service_type_id = (SELECT id FROM service_types WHERE code = 'GENERAL' LIMIT 1) "
        "WHERE service_type_id IS NULL"
    )
    op.alter_column(
        "invoices",
        "service_type_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
