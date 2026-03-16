"""BillingIngester: load SIHOS Excel and upsert invoices into PostgreSQL."""
from __future__ import annotations

import io
import logging

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Admin, Contract, Institution, Service
from app.models.invoice import Invoice
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
    save_mappings_only: bool = False,
) -> dict:
    """
    Full ingestion pipeline for SIHOS Excel (new uppercase format).

    Optimized to minimize DB round-trips:
    1. Parse + normalize Excel
    2. Pre-load existing admins/contracts/services into memory (3 queries)
    3. Bulk-insert only the NEW admins/contracts/services (3 queries max)
    4. Build invoice_map entirely in memory (0 DB calls)
    5. Bulk-insert all invoices in one statement
    """
    inst_repo = InstitutionRepo(db)
    rules_repo = RulesRepo(db)

    default_fs = await rules_repo.get_folder_status_by_status(_DEFAULT_FOLDER_STATUS)
    if not default_fs:
        raise RuntimeError(f"Folder status '{_DEFAULT_FOLDER_STATUS}' not found — run seeds first.")

    raw_df = load_excel(file_bytes)
    df = _normalize(raw_df)
    skipped = int(df["FECHA"].isna().sum())

    # ── Phase 1: collect unique raw strings from the Excel ────────────────
    col = lambda name: df[name].str.strip().dropna() if name in df.columns else pd.Series(dtype=str)

    raw_admins: set[str]    = set(col("ADMINISTRADORA").unique()) - {""}
    raw_contracts: set[str] = set(col("CONTRATO").unique()) - {""}
    raw_services: set[str]  = set(col("SERVICIO").unique()) - {""}

    # ── Phase 2: pre-load existing rows (3 queries total) ────────────────
    adm_cache: dict[str, Admin]    = {a.raw_admin:    a for a in await inst_repo.get_admins(institution.id)}
    ctr_cache: dict[str, Contract] = {c.raw_contract: c for c in await inst_repo.get_contracts(institution.id)}
    svc_cache: dict[str, Service]  = {s.raw_service:  s for s in await inst_repo.get_services(institution.id)}

    # ── Phase 3: bulk-insert only new entries ────────────────────────────
    new_admins    = raw_admins    - adm_cache.keys()
    new_contracts = raw_contracts - ctr_cache.keys()
    new_services  = raw_services  - svc_cache.keys()

    if new_admins:
        await db.execute(
            pg_insert(Admin)
            .values([{"institution_id": institution.id, "raw_admin": r} for r in new_admins])
            .on_conflict_do_nothing()
        )
        await db.flush()
        adm_cache = {a.raw_admin: a for a in await inst_repo.get_admins(institution.id)}

    if new_contracts:
        await db.execute(
            pg_insert(Contract)
            .values([{"institution_id": institution.id, "raw_contract": r} for r in new_contracts])
            .on_conflict_do_nothing()
        )
        await db.flush()
        ctr_cache = {c.raw_contract: c for c in await inst_repo.get_contracts(institution.id)}

    if new_services:
        await db.execute(
            pg_insert(Service)
            .values([
                {"institution_id": institution.id, "raw_service": r, "service_type_id": None}
                for r in new_services
            ])
            .on_conflict_do_nothing()
        )
        await db.flush()
        svc_cache = {s.raw_service: s for s in await inst_repo.get_services(institution.id)}

    # Track unknowns for the summary report
    unknown_admins    = [r for r in raw_admins    if adm_cache.get(r) and adm_cache[r].canonical_admin is None]
    unknown_contracts = [r for r in raw_contracts if ctr_cache.get(r) and ctr_cache[r].canonical_contract is None]
    unknown_services  = [r for r in raw_services  if svc_cache.get(r) and svc_cache[r].service_type_id is None]

    if scan_only:
        if save_mappings_only:
            await db.commit()
            logger.info(
                "ingest (mappings-only): institution=%s saved raw admins/contracts/services",
                institution.name,
            )
        return {
            "scan_only": True,
            "save_mappings_only": save_mappings_only,
            "inserted": 0,
            "skipped": skipped,
            "unknown_admins": unknown_admins,
            "unknown_contracts": unknown_contracts,
            "unknown_services": unknown_services,
        }

    # ── Phase 4: build invoice_map entirely in memory ────────────────────
    service_types = await rules_repo.get_service_types()
    priority_map: dict[int, int] = {st.id: st.priority for st in service_types}

    invoice_map: dict[str, dict] = {}

    for _, row in df.iterrows():
        invoice_date = row.get("FECHA")
        if not invoice_date:
            continue

        invoice_number = str(row["FACTURA"])
        raw_admin    = str(row.get("ADMINISTRADORA", "") or "").strip()
        raw_contract = str(row.get("CONTRATO", "") or "").strip()
        raw_service  = str(row.get("SERVICIO", "") or "").strip()

        admin    = adm_cache.get(raw_admin)
        contract = ctr_cache.get(raw_contract) if raw_contract else None
        service  = svc_cache.get(raw_service)  if raw_service  else None
        service_type_id = service.service_type_id if service else None

        if invoice_number not in invoice_map:
            invoice_map[invoice_number] = {
                "date":             invoice_date,
                "id_type":          str(row.get("DOCUMENTO", "") or "")[:10],
                "id_number":        str(row.get("NUMERO", "") or "")[:50],
                "patient_name":     str(row.get("PACIENTE", "") or "")[:300],
                "employee":         str(row.get("OPERARIO", "") or "")[:200] or None,
                "admin_id":         admin.id if admin else None,
                "contract_id":      contract.id if contract else None,
                "folder_status_id": default_fs.id,
                "_service_type_ids": set(),
            }

        if service_type_id is not None:
            invoice_map[invoice_number]["_service_type_ids"].add(service_type_id)

    # ── Phase 5: bulk-insert all invoices in one statement ───────────────
    invoice_values = []
    for invoice_number, data in invoice_map.items():
        st_ids: set[int] = data.pop("_service_type_ids")
        best_st_id = max(st_ids, key=lambda sid: priority_map.get(sid, 0)) if st_ids else None
        data["service_type_id"] = best_st_id
        invoice_values.append({
            "audit_period_id": period_id,
            "invoice_number":  invoice_number,
            **data,
        })

    inserted = 0
    if invoice_values:
        await db.execute(
            pg_insert(Invoice)
            .values(invoice_values)
            .on_conflict_do_nothing(index_elements=["audit_period_id", "invoice_number"])
        )
        inserted = len(invoice_values)

    await db.commit()
    logger.info(
        "ingest: institution=%s period_id=%s inserted=%d skipped=%d",
        institution.name, period_id, inserted, skipped,
    )
    return {
        "scan_only": False,
        "inserted": inserted,
        "skipped": skipped,
        "unknown_admins": unknown_admins,
        "unknown_contracts": unknown_contracts,
        "unknown_services": unknown_services,
    }
