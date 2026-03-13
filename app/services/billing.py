"""BillingIngester: load SIHOS Excel and upsert invoices into PostgreSQL."""
from __future__ import annotations

import io
import logging

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Institution
from app.repositories.institution_repo import InstitutionRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.repositories.rules_repo import RulesRepo

logger = logging.getLogger(__name__)

# Columns expected in the SIHOS Excel export
_SIHOS_COLUMNS = [
    "Fecha", "Doc", "No Doc", "Documento", "Numero",
    "Paciente", "Administradora", "Contrato", "Operario",
]

_DEFAULT_SERVICE_TYPE = "GENERAL"
_DEFAULT_FOLDER_STATUS = "PRESENTE"


def load_excel(file_bytes: bytes) -> pd.DataFrame:
    """Read SIHOS Excel from raw bytes into a DataFrame."""
    buf = io.BytesIO(file_bytes)
    df = pd.read_excel(buf, dtype=str)
    available = [c for c in _SIHOS_COLUMNS if c in df.columns]
    return df[available].copy()


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Strip blanks, build invoice_number composite key."""
    doc = df["Doc"].str.strip()
    mask = (
        doc.notna() & doc.ne("")
        & df["No Doc"].notna()
        & df["Administradora"].notna()
    )
    df = df[mask].copy()
    df["Doc"] = doc[mask].str.upper()
    df["No Doc"] = (
        pd.to_numeric(df["No Doc"], errors="coerce").astype("Int64").astype(str)
    )
    df["invoice_number"] = df["Doc"] + df["No Doc"]

    # Parse date
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    return df


async def ingest(
    file_bytes: bytes,
    institution: Institution,
    period_id: int,
    db: AsyncSession,
) -> dict:
    """
    Full ingestion pipeline for SIHOS Excel.

    1. Parse Excel
    2. For each row: upsert Admin and Contract (institution-level)
    3. Skip rows where canonical_admin is NULL (user hasn't mapped it yet)
    4. Upsert Invoice with FK references
    5. Return summary dict
    """
    inst_repo = InstitutionRepo(db)
    inv_repo = InvoiceRepo(db)
    rules_repo = RulesRepo(db)

    # Look up default IDs
    default_st = await rules_repo.get_service_type_by_code(_DEFAULT_SERVICE_TYPE)
    default_fs = await rules_repo.get_folder_status_by_status(_DEFAULT_FOLDER_STATUS)
    if not default_st:
        raise RuntimeError(f"Service type '{_DEFAULT_SERVICE_TYPE}' not found — run seeds first.")
    if not default_fs:
        raise RuntimeError(f"Folder status '{_DEFAULT_FOLDER_STATUS}' not found — run seeds first.")

    raw_df = load_excel(file_bytes)
    df = _normalize(raw_df)

    inserted = 0
    skipped = 0
    unknown_admins: list[str] = []
    unknown_contracts: list[str] = []

    for _, row in df.iterrows():
        raw_admin = str(row.get("Administradora", "") or "").strip()
        raw_contract = str(row.get("Contrato", "") or "").strip()
        invoice_number = str(row["invoice_number"])
        invoice_date = row.get("Fecha")

        if not invoice_date:
            skipped += 1
            continue

        # Upsert admin
        admin = await inst_repo.upsert_admin(institution.id, raw_admin)
        if admin.canonical_admin is None:
            if raw_admin not in unknown_admins:
                unknown_admins.append(raw_admin)
            skipped += 1
            continue  # don't load until user maps it

        # Upsert contract (institution-level, keyed by raw_contract string)
        contract = await inst_repo.upsert_contract(institution.id, raw_contract) if raw_contract else None
        if contract and contract.canonical_contract is None and raw_contract:
            if raw_contract not in unknown_contracts:
                unknown_contracts.append(raw_contract)
            # Still load — contract mapping is optional

        invoice_data = {
            "date":            invoice_date,
            "id_type":         str(row.get("Documento", "") or "")[:10],
            "id_number":       str(row.get("Numero", "") or "")[:50],
            "patient_name":    str(row.get("Paciente", "") or "")[:300],
            "employee":        str(row.get("Operario", "") or "")[:200] or None,
            "admin_id":        admin.id,
            "contract_id":     contract.id if contract else None,
            "service_type_id": default_st.id,
            "folder_status_id": default_fs.id,
        }

        await inv_repo.upsert_invoice(period_id, invoice_number, invoice_data)
        inserted += 1

    await db.commit()
    logger.info(
        "ingest: institution=%s period_id=%s inserted=%d skipped=%d",
        institution.name, period_id, inserted, skipped,
    )
    return {
        "inserted": inserted,
        "skipped": skipped,
        "unknown_admins": unknown_admins,
        "unknown_contracts": unknown_contracts,
    }
