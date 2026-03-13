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

# Columns expected in the new SIHOS Excel export (uppercase format)
_SIHOS_COLUMNS = [
    "FACTURA", "FECHA", "DOCUMENTO", "NUMERO", "PACIENTE",
    "ADMINISTRADORA", "CONTRATO", "SERVICIO", "OPERARIO",
]

_DEFAULT_FOLDER_STATUS = "PRESENTE"


def load_excel(file_bytes: bytes) -> pd.DataFrame:
    """Read SIHOS Excel from raw bytes into a DataFrame."""
    buf = io.BytesIO(file_bytes)
    df = pd.read_excel(buf, dtype=str)
    available = [c for c in _SIHOS_COLUMNS if c in df.columns]
    return df[available].copy()


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Strip blanks and validate the FACTURA column."""
    factura = df["FACTURA"].str.strip().str.upper()
    mask = factura.notna() & factura.ne("") & df["ADMINISTRADORA"].notna()
    df = df[mask].copy()
    df["FACTURA"] = factura[mask]
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce").dt.date
    return df


async def ingest(
    file_bytes: bytes,
    institution: Institution,
    period_id: int,
    db: AsyncSession,
    scan_only: bool = False,
) -> dict:
    """
    Full ingestion pipeline for SIHOS Excel (new uppercase format).

    1. Parse Excel
    2. For each row: upsert Admin, Contract, Service
    3. Skip rows where canonical_admin is NULL (user hasn't mapped it yet)
    4. Upsert Invoice with FK references and resolved service_type_id
    5. Return summary dict
    """
    inst_repo = InstitutionRepo(db)
    inv_repo = InvoiceRepo(db)
    rules_repo = RulesRepo(db)

    # Look up default folder status
    default_fs = await rules_repo.get_folder_status_by_status(_DEFAULT_FOLDER_STATUS)
    if not default_fs:
        raise RuntimeError(f"Folder status '{_DEFAULT_FOLDER_STATUS}' not found — run seeds first.")

    raw_df = load_excel(file_bytes)
    df = _normalize(raw_df)

    inserted = 0
    skipped = 0
    unknown_admins: list[str] = []
    unknown_contracts: list[str] = []
    unknown_services: list[str] = []

    for _, row in df.iterrows():
        raw_admin = str(row.get("ADMINISTRADORA", "") or "").strip()
        raw_contract = str(row.get("CONTRATO", "") or "").strip()
        raw_service = str(row.get("SERVICIO", "") or "").strip()
        invoice_number = str(row["FACTURA"])
        invoice_date = row.get("FECHA")

        if not invoice_date:
            skipped += 1
            continue

        # Upsert admin — record unmapped but always continue
        admin = await inst_repo.upsert_admin(institution.id, raw_admin)
        if admin.canonical_admin is None and raw_admin not in unknown_admins:
            unknown_admins.append(raw_admin)

        # Upsert contract — record unmapped but always continue
        contract = await inst_repo.upsert_contract(institution.id, raw_contract) if raw_contract else None
        if contract and contract.canonical_contract is None and raw_contract not in unknown_contracts:
            unknown_contracts.append(raw_contract)

        # Upsert service — record unmapped but always continue
        service = await inst_repo.upsert_service(institution.id, raw_service) if raw_service else None
        service_type_id = service.service_type_id if service else None
        if service and service_type_id is None and raw_service not in unknown_services:
            unknown_services.append(raw_service)

        if scan_only:
            continue

        invoice_data = {
            "date":             invoice_date,
            "id_type":          str(row.get("DOCUMENTO", "") or "")[:10],
            "id_number":        str(row.get("NUMERO", "") or "")[:50],
            "patient_name":     str(row.get("PACIENTE", "") or "")[:300],
            "employee":         str(row.get("OPERARIO", "") or "")[:200] or None,
            "admin_id":         admin.id,
            "contract_id":      contract.id if contract else None,
            "service_type_id":  service_type_id,
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
        "scan_only": scan_only,
        "inserted": inserted,
        "skipped": skipped,
        "unknown_admins": unknown_admins,
        "unknown_contracts": unknown_contracts,
        "unknown_services": unknown_services,
    }
