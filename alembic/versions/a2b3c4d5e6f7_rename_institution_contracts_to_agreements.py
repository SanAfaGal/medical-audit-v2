"""rename institution_contracts to agreements

Revision ID: a2b3c4d5e6f7
Revises: f7b8c9d0e1f2
Create Date: 2026-03-16
"""

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Deduplicate institution_contracts: for each (administrator_id, contract_id) keep lowest id
    #    and redirect invoices pointing to duplicates to the kept row.
    op.execute("""
        UPDATE invoices
        SET institution_contract_id = keeper.id
        FROM (
            SELECT DISTINCT ON (administrator_id, contract_id) id, administrator_id, contract_id
            FROM institution_contracts
            ORDER BY administrator_id, contract_id, id ASC
        ) AS keeper
        JOIN institution_contracts ic
            ON ic.administrator_id = keeper.administrator_id
            AND ic.contract_id = keeper.contract_id
            AND ic.id != keeper.id
        WHERE invoices.institution_contract_id = ic.id
    """)

    # 2. Delete duplicate rows
    op.execute("""
        DELETE FROM institution_contracts
        WHERE id NOT IN (
            SELECT DISTINCT ON (administrator_id, contract_id) id
            FROM institution_contracts
            ORDER BY administrator_id, contract_id, id ASC
        )
    """)

    # 3. Drop old unique constraint
    op.execute("""
        ALTER TABLE institution_contracts
        DROP CONSTRAINT IF EXISTS institution_contracts_institution_id_administrator_id_cont_key
    """)

    # 4. Drop institution_id column
    op.execute("ALTER TABLE institution_contracts DROP COLUMN institution_id")

    # 5. Add new unique constraint
    op.execute("""
        ALTER TABLE institution_contracts
        ADD CONSTRAINT agreements_administrator_id_contract_id_key
        UNIQUE (administrator_id, contract_id)
    """)

    # 6. Rename table
    op.execute("ALTER TABLE institution_contracts RENAME TO agreements")

    # 7. Rename column in invoices
    op.execute("ALTER TABLE invoices RENAME COLUMN institution_contract_id TO agreement_id")


def downgrade():
    # 1. Rename column back
    op.execute("ALTER TABLE invoices RENAME COLUMN agreement_id TO institution_contract_id")

    # 2. Rename table back
    op.execute("ALTER TABLE agreements RENAME TO institution_contracts")

    # 3. Drop new unique constraint
    op.execute("""
        ALTER TABLE institution_contracts
        DROP CONSTRAINT IF EXISTS agreements_administrator_id_contract_id_key
    """)

    # 4. Add back institution_id column (nullable — can't fully restore values without audit_periods join)
    op.execute("""
        ALTER TABLE institution_contracts
        ADD COLUMN institution_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE
    """)

    # 5. Try to populate institution_id from invoices -> audit_periods
    op.execute("""
        UPDATE institution_contracts ic
        SET institution_id = sub.institution_id
        FROM (
            SELECT DISTINCT inv.institution_contract_id AS ic_id, p.institution_id
            FROM invoices inv
            JOIN audit_periods p ON p.id = inv.audit_period_id
            WHERE inv.institution_contract_id IS NOT NULL
        ) AS sub
        WHERE ic.id = sub.ic_id
    """)

    # 6. Re-add old unique constraint
    op.execute("""
        ALTER TABLE institution_contracts
        ADD CONSTRAINT institution_contracts_institution_id_administrator_id_cont_key
        UNIQUE (institution_id, administrator_id, contract_id)
    """)
