"""BillingIngester: load SIHOS Excel and upsert invoices into PostgreSQL."""
from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hospital import Hospital
from app.repositories.hospital_repo import HospitalRepo
from app.repositories.invoice_repo import InvoiceRepo

logger = logging.getLogger(__name__)

# Columns expected in the SIHOS Excel export
_SIHOS_COLUMNS = [
    "Fecha", "Doc", "No Doc", "Documento", "Numero",
    "Paciente", "Administradora", "Contrato", "Operario",
]


def load_excel(file_bytes: bytes) -> pd.DataFrame:
    """Read SIHOS Excel from raw bytes into a DataFrame."""
    buf = io.BytesIO(file_bytes)
    df = pd.read_excel(buf, dtype=str)
    # Normalize column names — keep only the ones we need
    available = [c for c in _SIHOS_COLUMNS if c in df.columns]
    return df[available].copy()


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Strip blanks, build Factura composite key."""
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
    df["Factura"] = df["Doc"] + df["No Doc"]
    return df


async def ingest(
    file_bytes: bytes,
    hospital: Hospital,
    period_code: str,
    db: AsyncSession,
) -> dict:
    """
    Full ingestion pipeline:
    1. Parse Excel
    2. For each row: upsert Admin, upsert Contract
    3. Skip rows where canonical admin is NULL
    4. Build ruta and upsert Invoice
    5. Return summary dict

    Returns:
        {
          "inserted": int,
          "skipped": int,
          "unknown_admins": list[str],
          "unknown_contracts": list[str],
        }
    """
    hospital_repo = HospitalRepo(db)
    invoice_repo = InvoiceRepo(db)

    raw_df = load_excel(file_bytes)
    df = _normalize(raw_df)

    period = await invoice_repo.get_or_create_period(hospital.id, period_code)

    inserted = 0
    skipped = 0
    unknown_admins: list[str] = []
    unknown_contracts: list[str] = []

    for _, row in df.iterrows():
        raw_admin = str(row.get("Administradora", "") or "").strip()
        raw_contract = str(row.get("Contrato", "") or "").strip()
        factura = str(row["Factura"])

        # Upsert admin
        admin = await hospital_repo.upsert_admin(hospital.id, raw_admin)
        if admin.canonical_value is None:
            if raw_admin not in unknown_admins:
                unknown_admins.append(raw_admin)
            skipped += 1
            continue  # don't load until user maps it

        # Upsert contract (may be empty — use empty string as key)
        contract = await hospital_repo.upsert_contract(admin.id, raw_contract)
        if contract.canonical_value is None and raw_contract:
            if raw_contract not in unknown_contracts:
                unknown_contracts.append(raw_contract)
            # Still load — contract canonical can be empty (some invoices have none)

        # Build filesystem path
        canonical_admin = admin.canonical_value
        canonical_contract = contract.canonical_value or ""
        path = PurePosixPath(canonical_admin)
        if canonical_contract:
            path = path / canonical_contract
        ruta = str(path / factura)

        invoice_data = {
            "fecha":         str(row.get("Fecha", "") or ""),
            "documento":     str(row.get("Documento", "") or ""),
            "numero":        str(row.get("Numero", "") or ""),
            "paciente":      str(row.get("Paciente", "") or ""),
            "administradora": canonical_admin,
            "contrato":      canonical_contract or None,
            "operario":      str(row.get("Operario", "") or ""),
            "ruta":          ruta,
        }

        await invoice_repo.upsert_invoice(period.id, factura, invoice_data)
        inserted += 1

    await db.commit()
    logger.info(
        "ingest: hospital=%s period=%s inserted=%d skipped=%d",
        hospital.key, period_code, inserted, skipped,
    )
    return {
        "inserted": inserted,
        "skipped": skipped,
        "unknown_admins": unknown_admins,
        "unknown_contracts": unknown_contracts,
    }
