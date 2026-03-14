"""add logo columns to institutions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('institutions', sa.Column('logo_bytes', sa.LargeBinary(), nullable=True))
    op.add_column('institutions', sa.Column('logo_content_type', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('institutions', 'logo_content_type')
    op.drop_column('institutions', 'logo_bytes')
