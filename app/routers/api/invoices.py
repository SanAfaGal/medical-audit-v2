"""API router for invoices: list, filter, batch-update, ingest."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.hospital_repo import HospitalRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.schemas.invoice import (
    BatchStatusUpdate,
    InvoiceNotaUpdate,
    InvoiceOut,
    InvoiceStatusUpdate,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=dict)
async def list_invoices(
    hospital_key: str,
    period_code: str,
    folder_status: str | None = None,
    service_type_id: int | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(hospital_key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")

    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_or_create_period(hospital.id, period_code)
    invoices, total = await inv_repo.filter_invoices(
        period_id=period.id,
        folder_status=folder_status,
        service_type_id=service_type_id,
        search=search,
        page=page,
        page_size=page_size,
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [InvoiceOut.model_validate(inv) for inv in invoices],
    }


@router.patch("/{invoice_id}/status", response_model=InvoiceOut)
async def update_status(
    invoice_id: int,
    data: InvoiceStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    repo = InvoiceRepo(db)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(404, "Factura no encontrada")
    await repo.update_folder_status(invoice_id, data.folder_status)
    await db.commit()
    return await repo.get_by_id(invoice_id)


@router.patch("/{invoice_id}/nota", response_model=InvoiceOut)
async def update_nota(
    invoice_id: int,
    data: InvoiceNotaUpdate,
    db: AsyncSession = Depends(get_db),
):
    repo = InvoiceRepo(db)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise HTTPException(404, "Factura no encontrada")
    await repo.update_nota(invoice_id, data.nota)
    await db.commit()
    return await repo.get_by_id(invoice_id)


@router.post("/batch-status", status_code=200)
async def batch_update_status(data: BatchStatusUpdate, db: AsyncSession = Depends(get_db)):
    repo = InvoiceRepo(db)
    await repo.batch_update_status(data.invoice_ids, data.folder_status)
    await db.commit()
    return {"updated": len(data.invoice_ids)}


@router.post("/ingest", status_code=200)
async def ingest_excel(
    hospital_key: str = Form(...),
    period_code: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload and ingest a SIHOS Excel export."""
    from app.services.billing import ingest
    from app.repositories.hospital_repo import HospitalRepo

    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(hospital_key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")

    file_bytes = await file.read()
    result = await ingest(file_bytes, hospital, period_code, db)
    return result
