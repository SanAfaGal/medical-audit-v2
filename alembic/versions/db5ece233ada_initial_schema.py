"""initial schema

Revision ID: db5ece233ada
Revises:
Create Date: 2026-03-12 18:21:41.571413

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db5ece233ada'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Independent lookup tables first --

    op.create_table('service_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='10'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    op.create_table('doc_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=False),
        sa.Column('prefix', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    op.create_table('folder_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('status'),
    )

    # -- Institution and its children --

    op.create_table('institutions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('nit', sa.String(length=20), nullable=False),
        sa.Column('invoice_id_prefix', sa.String(length=20), nullable=False),
        sa.Column('sihos_base_url', sa.String(length=500), nullable=True),
        sa.Column('sihos_doc_code', sa.String(length=20), nullable=True),
        sa.Column('sihos_user', sa.String(length=200), nullable=True),
        sa.Column('sihos_password', sa.String(length=200), nullable=True),
        sa.Column('base_path', sa.String(length=500), nullable=True),
        sa.Column('drive_credentials_enc', sa.String(length=10000), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('nit'),
        sa.UniqueConstraint('invoice_id_prefix'),
    )

    op.create_table('admins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=True),
        sa.Column('raw_admin', sa.String(length=300), nullable=False),
        sa.Column('canonical_admin', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'raw_admin'),
    )

    op.create_table('contracts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('raw_contract', sa.String(length=300), nullable=False),
        sa.Column('canonical_contract', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'raw_contract'),
    )

    op.create_table('services',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('raw_service', sa.String(length=300), nullable=False),
        sa.Column('service_type_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_type_id'], ['service_types.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'raw_service'),
    )

    op.create_table('service_type_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('service_type_id', sa.Integer(), nullable=False),
        sa.Column('doc_type_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_type_id'], ['service_types.id']),
        sa.ForeignKeyConstraint(['doc_type_id'], ['doc_types.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'service_type_id', 'doc_type_id'),
    )

    # -- Periods and invoices --

    op.create_table('audit_periods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('period_label', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('institution_id', 'date_from', 'date_to', 'period_label'),
    )

    op.create_table('invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audit_period_id', sa.Integer(), nullable=False),
        sa.Column('invoice_number', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('id_type', sa.String(length=10), nullable=False),
        sa.Column('id_number', sa.String(length=50), nullable=False),
        sa.Column('patient_name', sa.String(length=300), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('contract_id', sa.Integer(), nullable=True),
        sa.Column('service_type_id', sa.Integer(), nullable=False),
        sa.Column('employee', sa.String(length=200), nullable=True),
        sa.Column('folder_status_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['audit_period_id'], ['audit_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id']),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id']),
        sa.ForeignKeyConstraint(['service_type_id'], ['service_types.id']),
        sa.ForeignKeyConstraint(['folder_status_id'], ['folder_statuses.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('audit_period_id', 'invoice_number'),
    )

    op.create_table('missing_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('doc_type_id', sa.Integer(), nullable=False),
        sa.Column('expected_path', sa.String(length=500), nullable=False),
        sa.Column('detected_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doc_type_id'], ['doc_types.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_id', 'doc_type_id'),
    )


def downgrade() -> None:
    op.drop_table('missing_files')
    op.drop_table('invoices')
    op.drop_table('audit_periods')
    op.drop_table('service_type_documents')
    op.drop_table('services')
    op.drop_table('contracts')
    op.drop_table('admins')
    op.drop_table('institutions')
    op.drop_table('folder_statuses')
    op.drop_table('doc_types')
    op.drop_table('service_types')
