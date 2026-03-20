"""normalize administrators and contracts tables

Revision ID: f7b8c9d0e1f2
Revises: e1f2a3b4c5d6
Create Date: 2026-03-16
"""

from alembic import op

revision = "f7b8c9d0e1f2"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create contract_types with seed data
    op.execute("""
        CREATE TABLE contract_types (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            description VARCHAR(200)
        )
    """)
    op.execute("""
        INSERT INTO contract_types (name, description) VALUES
            ('EPS', 'Entidad Promotora de Salud'),
            ('SOAT', 'Seguro Obligatorio de Accidentes de Tránsito'),
            ('ARL', 'Administradora de Riesgos Laborales')
    """)

    # 2. Create administrators (global)
    op.execute("""
        CREATE TABLE administrators (
            id SERIAL PRIMARY KEY,
            raw_name VARCHAR(300) NOT NULL UNIQUE,
            canonical_name VARCHAR(300)
        )
    """)

    # 3. Create contracts_global (will replace old contracts after data migration)
    op.execute("""
        CREATE TABLE contracts_global (
            id SERIAL PRIMARY KEY,
            raw_name VARCHAR(300) NOT NULL UNIQUE,
            canonical_name VARCHAR(300)
        )
    """)

    # 4. Create institution_contracts
    op.execute("""
        CREATE TABLE institution_contracts (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
            administrator_id INTEGER NOT NULL REFERENCES administrators(id),
            contract_id INTEGER NOT NULL REFERENCES contracts_global(id),
            contract_type_id INTEGER REFERENCES contract_types(id),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            UNIQUE (institution_id, administrator_id, contract_id)
        )
    """)

    # 5. Add institution_contract_id to invoices (nullable for migration)
    op.execute("""
        ALTER TABLE invoices ADD COLUMN institution_contract_id INTEGER
            REFERENCES institution_contracts(id)
    """)

    # 6. Populate administrators from admins (deduplicated by raw_admin)
    op.execute("""
        INSERT INTO administrators (raw_name, canonical_name)
        SELECT DISTINCT ON (raw_admin) raw_admin, canonical_admin
        FROM admins
        ORDER BY raw_admin, canonical_admin NULLS LAST
        ON CONFLICT (raw_name) DO NOTHING
    """)

    # 7. Populate contracts_global from contracts (deduplicated by raw_contract)
    op.execute("""
        INSERT INTO contracts_global (raw_name, canonical_name)
        SELECT DISTINCT ON (raw_contract) raw_contract, canonical_contract
        FROM contracts
        ORDER BY raw_contract, canonical_contract NULLS LAST
        ON CONFLICT (raw_name) DO NOTHING
    """)

    # 8. Build institution_contracts from existing invoice data
    #    (invoices with both admin_id and contract_id)
    op.execute("""
        INSERT INTO institution_contracts
            (institution_id, administrator_id, contract_id, contract_type_id)
        SELECT DISTINCT
            p.institution_id,
            adm.id,
            cg.id,
            ct.id
        FROM invoices inv
        JOIN audit_periods p ON p.id = inv.audit_period_id
        JOIN admins old_adm ON old_adm.id = inv.admin_id
        JOIN administrators adm ON adm.raw_name = old_adm.raw_admin
        JOIN contracts old_c ON old_c.id = inv.contract_id
        JOIN contracts_global cg ON cg.raw_name = old_c.raw_contract
        LEFT JOIN contract_types ct ON ct.name = old_adm.type
        WHERE inv.admin_id IS NOT NULL AND inv.contract_id IS NOT NULL
        ON CONFLICT (institution_id, administrator_id, contract_id) DO NOTHING
    """)

    # 9. Update invoices.institution_contract_id
    op.execute("""
        UPDATE invoices inv
        SET institution_contract_id = ic.id
        FROM institution_contracts ic
        JOIN audit_periods p ON p.id = inv.audit_period_id
        JOIN admins old_adm ON old_adm.id = inv.admin_id
        JOIN administrators adm ON adm.raw_name = old_adm.raw_admin
        JOIN contracts old_c ON old_c.id = inv.contract_id
        JOIN contracts_global cg ON cg.raw_name = old_c.raw_contract
        WHERE ic.institution_id = p.institution_id
          AND ic.administrator_id = adm.id
          AND ic.contract_id = cg.id
          AND inv.admin_id IS NOT NULL
          AND inv.contract_id IS NOT NULL
    """)

    # 10. Drop old columns and tables
    op.execute("ALTER TABLE invoices DROP COLUMN admin_id")
    op.execute("ALTER TABLE invoices DROP COLUMN contract_id")
    op.execute("DROP TABLE admins")
    op.execute("DROP TABLE contracts")

    # 11. Rename contracts_global → contracts
    op.execute("ALTER TABLE contracts_global RENAME TO contracts")


def downgrade():
    # Reverse: recreate old admins and contracts tables, restore invoice columns

    # 1. Rename contracts back to contracts_global temporarily
    op.execute("ALTER TABLE contracts RENAME TO contracts_global")

    # 2. Recreate old contracts table
    op.execute("""
        CREATE TABLE contracts (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
            raw_contract VARCHAR(300) NOT NULL,
            canonical_contract VARCHAR(300),
            UNIQUE (institution_id, raw_contract)
        )
    """)

    # 3. Recreate admins table
    op.execute("""
        CREATE TABLE admins (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
            type VARCHAR(20),
            raw_admin VARCHAR(300) NOT NULL,
            canonical_admin VARCHAR(300),
            UNIQUE (institution_id, raw_admin)
        )
    """)

    # 4. Populate old contracts from institution_contracts + contracts_global
    op.execute("""
        INSERT INTO contracts (institution_id, raw_contract, canonical_contract)
        SELECT DISTINCT ic.institution_id, cg.raw_name, cg.canonical_name
        FROM institution_contracts ic
        JOIN contracts_global cg ON cg.id = ic.contract_id
        ON CONFLICT (institution_id, raw_contract) DO NOTHING
    """)

    # 5. Populate old admins from institution_contracts + administrators + contract_types
    op.execute("""
        INSERT INTO admins (institution_id, raw_admin, canonical_admin, type)
        SELECT DISTINCT ic.institution_id, adm.raw_name, adm.canonical_name, ct.name
        FROM institution_contracts ic
        JOIN administrators adm ON adm.id = ic.administrator_id
        LEFT JOIN contract_types ct ON ct.id = ic.contract_type_id
        ON CONFLICT (institution_id, raw_admin) DO NOTHING
    """)

    # 6. Add back admin_id and contract_id to invoices
    op.execute("ALTER TABLE invoices ADD COLUMN admin_id INTEGER REFERENCES admins(id)")
    op.execute("ALTER TABLE invoices ADD COLUMN contract_id INTEGER REFERENCES contracts(id)")

    # 7. Restore invoice admin_id and contract_id from institution_contracts
    op.execute("""
        UPDATE invoices inv
        SET
            admin_id = a.id,
            contract_id = c.id
        FROM institution_contracts ic
        JOIN audit_periods p ON p.id = inv.audit_period_id
        JOIN administrators adm ON adm.id = ic.administrator_id
        JOIN admins a ON a.institution_id = p.institution_id AND a.raw_admin = adm.raw_name
        JOIN contracts_global cg ON cg.id = ic.contract_id
        JOIN contracts c ON c.institution_id = p.institution_id AND c.raw_contract = cg.raw_name
        WHERE inv.institution_contract_id = ic.id
    """)

    # 8. Drop institution_contract_id from invoices
    op.execute("ALTER TABLE invoices DROP COLUMN institution_contract_id")

    # 9. Drop new tables
    op.execute("DROP TABLE institution_contracts")
    op.execute("DROP TABLE contracts_global")
    op.execute("DROP TABLE administrators")
    op.execute("DROP TABLE contract_types")
