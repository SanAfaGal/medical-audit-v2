"""API router for audit periods."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.paths import to_container_path
from app.repositories.institution_repo import InstitutionRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.repositories.rules_repo import RulesRepo
from app.schemas.invoice import PeriodCreate, PeriodOut

router = APIRouter(prefix="/institutions", tags=["periods"])
logger = logging.getLogger(__name__)

_PERIOD_SUBDIRS = ("DRIVE", "STAGE", "AUDIT")


def _create_period_dirs(base_path: str, period_label: str) -> list[str]:
    """Create DRIVE, STAGE and AUDIT under base_path/period_label.

    Returns the paths that were created (or already existed).
    Raises OSError if the filesystem operation fails.
    """
    root = Path(base_path) / period_label
    created = []
    for name in _PERIOD_SUBDIRS:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        created.append(str(d))
    return created


@router.get("/{institution_id}/periods", response_model=list[PeriodOut])
async def list_periods(institution_id: int, db: AsyncSession = Depends(get_db)):
    inst_repo = InstitutionRepo(db)
    institution = await inst_repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    inv_repo = InvoiceRepo(db)
    return await inv_repo.get_periods(institution_id)


@router.post("/{institution_id}/periods", response_model=PeriodOut, status_code=201)
async def create_period(
    institution_id: int, data: PeriodCreate, db: AsyncSession = Depends(get_db)
):
    inst_repo = InstitutionRepo(db)
    institution = await inst_repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")

    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_or_create_period(
        institution_id, data.date_from, data.date_to, data.period_label
    )
    await db.commit()

    sys_settings = await RulesRepo(db).get_system_settings()
    audit_data_root = sys_settings.audit_data_root if sys_settings and sys_settings.audit_data_root else None
    if audit_data_root:
        inst_root = str(to_container_path(audit_data_root) / institution.name)
        try:
            created = await asyncio.to_thread(
                _create_period_dirs, inst_root, data.period_label
            )
            for path in created:
                logger.info("Carpeta creada: %s", path)
        except OSError as exc:
            # Non-fatal: log and continue — period is already persisted
            logger.warning(
                "No se pudieron crear las carpetas del período %s: %s",
                data.period_label, exc,
            )
    else:
        logger.warning(
            "audit_data_root no configurado; carpetas del período no creadas.",
        )

    return period


@router.delete("/periods/{period_id}", status_code=204)
async def delete_period(period_id: int, db: AsyncSession = Depends(get_db)):
    inv_repo = InvoiceRepo(db)
    await inv_repo.delete_period(period_id)
    await db.commit()
