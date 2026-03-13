"""add_prefix_corrections

Revision ID: 3c5f8a2d1e04
Revises: 7929537df5a9
Create Date: 2026-03-13 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3c5f8a2d1e04"
down_revision: Union[str, None] = "7929537df5a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default corrections provided by the domain team
_DEFAULT_CORRECTIONS = [
    ("OPD",  "OPF"),
    ("FVE",  "FEV"),
    ("FHEV", "HEV"),
    ("PED",  "PDE"),
    ("OHEV", "HEV"),
    ("FOPF", "OPF"),
    ("OPG",  "OPF"),
    ("FVS",  "FEV"),
    ("FEPI", "EPI"),
    ("HVE",  "HEV"),
    ("OTR",  "OPF"),
]


def upgrade() -> None:
    prefix_corrections = op.create_table(
        "prefix_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wrong_prefix", sa.String(20), nullable=False),
        sa.Column("correct_prefix", sa.String(20), nullable=False),
        sa.Column("notes", sa.String(200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wrong_prefix"),
    )
    op.bulk_insert(
        prefix_corrections,
        [{"wrong_prefix": w, "correct_prefix": c, "notes": None} for w, c in _DEFAULT_CORRECTIONS],
    )


def downgrade() -> None:
    op.drop_table("prefix_corrections")
