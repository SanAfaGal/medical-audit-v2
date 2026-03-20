"""drop system_settings table — ruta de auditoría ahora viene del bind mount en .env

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-14
"""

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("system_settings")


def downgrade():
    import sqlalchemy as sa

    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_data_root", sa.String(500), nullable=True),
    )
