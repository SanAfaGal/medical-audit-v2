"""add invoice status integrity triggers — enforce PRESENTE/PENDIENTE invariant

Ensures that invoices with unresolved findings (missing_files.resolved_at IS NULL)
are always PENDIENTE, and invoices without unresolved findings are always PRESENTE.
Only PRESENTE and PENDIENTE statuses are managed; AUDITADA, FALTANTE, ANULAR, REVISAR
are left untouched.

Revision ID: a7f3b1e2c8d5
Revises: f6a7b8c9d0e1
Create Date: 2026-03-16
"""
from alembic import op

revision = 'a7f3b1e2c8d5'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------ #
    # 1. Repair existing inconsistent data                                 #
    # ------------------------------------------------------------------ #

    # PRESENTE with unresolved findings → PENDIENTE
    op.execute("""
        UPDATE invoices
        SET folder_status_id = (SELECT id FROM folder_statuses WHERE status = 'PENDIENTE')
        WHERE folder_status_id = (SELECT id FROM folder_statuses WHERE status = 'PRESENTE')
          AND EXISTS (
              SELECT 1 FROM missing_files
              WHERE invoice_id = invoices.id AND resolved_at IS NULL
          )
    """)

    # PENDIENTE without any unresolved findings → PRESENTE
    op.execute("""
        UPDATE invoices
        SET folder_status_id = (SELECT id FROM folder_statuses WHERE status = 'PRESENTE')
        WHERE folder_status_id = (SELECT id FROM folder_statuses WHERE status = 'PENDIENTE')
          AND NOT EXISTS (
              SELECT 1 FROM missing_files
              WHERE invoice_id = invoices.id AND resolved_at IS NULL
          )
    """)

    # ------------------------------------------------------------------ #
    # 2. Trigger on missing_files → sync invoice status after changes      #
    # ------------------------------------------------------------------ #

    op.execute("""
        CREATE OR REPLACE FUNCTION sync_invoice_status_from_findings()
        RETURNS TRIGGER AS $$
        DECLARE
            v_invoice_id    INTEGER;
            v_current_id    INTEGER;
            v_presente_id   INTEGER;
            v_pendiente_id  INTEGER;
            v_open_count    INTEGER;
        BEGIN
            -- Determine the affected invoice_id for each DML type
            IF TG_OP = 'DELETE' THEN
                v_invoice_id := OLD.invoice_id;
            ELSE
                v_invoice_id := NEW.invoice_id;
            END IF;

            -- Resolve status IDs
            SELECT id INTO v_presente_id  FROM folder_statuses WHERE status = 'PRESENTE';
            SELECT id INTO v_pendiente_id FROM folder_statuses WHERE status = 'PENDIENTE';

            -- Get current status of the invoice
            SELECT folder_status_id INTO v_current_id
            FROM invoices WHERE id = v_invoice_id;

            -- Only manage PRESENTE / PENDIENTE — leave other statuses alone
            IF v_current_id NOT IN (v_presente_id, v_pendiente_id) THEN
                RETURN NEW;
            END IF;

            -- Count remaining unresolved findings for this invoice
            SELECT COUNT(*) INTO v_open_count
            FROM missing_files
            WHERE invoice_id = v_invoice_id AND resolved_at IS NULL;

            IF v_open_count > 0 AND v_current_id = v_presente_id THEN
                UPDATE invoices
                SET folder_status_id = v_pendiente_id
                WHERE id = v_invoice_id;
            ELSIF v_open_count = 0 AND v_current_id = v_pendiente_id THEN
                UPDATE invoices
                SET folder_status_id = v_presente_id
                WHERE id = v_invoice_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_sync_invoice_status_from_findings
        AFTER INSERT OR UPDATE OR DELETE ON missing_files
        FOR EACH ROW EXECUTE FUNCTION sync_invoice_status_from_findings();
    """)

    # ------------------------------------------------------------------ #
    # 3. Guard trigger on invoices → block bad PRESENTE updates            #
    # ------------------------------------------------------------------ #

    op.execute("""
        CREATE OR REPLACE FUNCTION guard_invoice_presente_status()
        RETURNS TRIGGER AS $$
        DECLARE
            v_presente_id   INTEGER;
            v_pendiente_id  INTEGER;
        BEGIN
            SELECT id INTO v_presente_id  FROM folder_statuses WHERE status = 'PRESENTE';
            SELECT id INTO v_pendiente_id FROM folder_statuses WHERE status = 'PENDIENTE';

            -- Only intercept attempts to set status to PRESENTE
            IF NEW.folder_status_id = v_presente_id THEN
                IF EXISTS (
                    SELECT 1 FROM missing_files
                    WHERE invoice_id = NEW.id AND resolved_at IS NULL
                ) THEN
                    -- Silently correct to PENDIENTE instead of raising an error
                    NEW.folder_status_id := v_pendiente_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_guard_invoice_presente_status
        BEFORE UPDATE OF folder_status_id ON invoices
        FOR EACH ROW EXECUTE FUNCTION guard_invoice_presente_status();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_guard_invoice_presente_status ON invoices")
    op.execute("DROP FUNCTION IF EXISTS guard_invoice_presente_status()")
    op.execute("DROP TRIGGER IF EXISTS trg_sync_invoice_status_from_findings ON missing_files")
    op.execute("DROP FUNCTION IF EXISTS sync_invoice_status_from_findings()")
    # Data repair is not reversed — state before migration may have been inconsistent
