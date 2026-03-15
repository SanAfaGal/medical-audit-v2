"""API router for invoices: list, filter, batch-update, ingest, export."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.finding_repo import MissingFileRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.schemas.invoice import (
    BatchStatusUpdate,
    InvoiceListItem,
    InvoiceOut,
    InvoiceStatusUpdate,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("/ids", response_model=list[int])
async def get_invoice_ids(
    period_id: int,
    folder_status_id: int | None = None,
    service_type_id: int | None = None,
    admin_canonical: str | None = None,
    admin_type: str | None = None,
    contract_canonical: str | None = None,
    search: str | None = None,
    has_finding_doc_type_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    repo = InvoiceRepo(db)
    return await repo.get_invoice_ids(
        audit_period_id=period_id,
        folder_status_id=folder_status_id,
        service_type_id=service_type_id,
        admin_canonical=admin_canonical,
        admin_type=admin_type,
        contract_canonical=contract_canonical,
        search=search,
        has_finding_doc_type_id=has_finding_doc_type_id,
    )


@router.get("/stats", response_model=dict)
async def get_stats(period_id: int, db: AsyncSession = Depends(get_db)):
    repo = InvoiceRepo(db)
    return await repo.get_stats(period_id)


@router.get("/findings-summary", response_model=list[dict])
async def get_findings_summary(period_id: int, db: AsyncSession = Depends(get_db)):
    repo = MissingFileRepo(db)
    return await repo.get_findings_summary(period_id)


@router.get("", response_model=dict)
async def list_invoices(
    period_id: int,
    folder_status_id: int | None = None,
    service_type_id: int | None = None,
    admin_canonical: str | None = None,
    admin_type: str | None = None,
    contract_canonical: str | None = None,
    search: str | None = None,
    has_finding_doc_type_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    inv_repo = InvoiceRepo(db)
    invoices, total = await inv_repo.filter_invoices(
        audit_period_id=period_id,
        folder_status_id=folder_status_id,
        service_type_id=service_type_id,
        admin_canonical=admin_canonical,
        admin_type=admin_type,
        contract_canonical=contract_canonical,
        search=search,
        has_finding_doc_type_id=has_finding_doc_type_id,
        page=page,
        page_size=page_size,
    )

    items = []
    for inv in invoices:
        items.append(InvoiceListItem(
            id=inv.id,
            invoice_number=inv.invoice_number,
            patient_name=inv.patient_name,
            admin_id=inv.admin_id,
            admin_canonical=inv.admin.canonical_admin if inv.admin else None,
            admin_type=inv.admin.type if inv.admin else None,
            contract_id=inv.contract_id,
            contract_canonical=inv.contract.canonical_contract if inv.contract else None,
            folder_status=inv.folder_status.status,
            folder_status_id=inv.folder_status_id,
            service_type_code=inv.service_type.code if inv.service_type else None,
            service_type_id=inv.service_type_id,
            missing_file_count=len([mf for mf in inv.missing_files if mf.resolved_at is None]),
            date=inv.date,
        ))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [item.model_dump() for item in items],
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
    await repo.update_folder_status(invoice_id, data.folder_status_id)
    await db.commit()
    return await repo.get_by_id(invoice_id)


@router.post("/batch-status", status_code=200)
async def batch_update_status(data: BatchStatusUpdate, db: AsyncSession = Depends(get_db)):
    repo = InvoiceRepo(db)
    await repo.batch_update_status(data.invoice_ids, data.folder_status_id)
    await db.commit()
    return {"updated": len(data.invoice_ids)}


@router.delete("/{invoice_id}", status_code=204)
async def delete_invoice(invoice_id: int, db: AsyncSession = Depends(get_db)):
    repo = InvoiceRepo(db)
    deleted = await repo.delete_invoice(invoice_id)
    if not deleted:
        raise HTTPException(404, "Factura no encontrada")
    await db.commit()


@router.post("/ingest", status_code=200)
async def ingest_excel(
    institution_id: int = Form(...),
    period_id: int = Form(...),
    file: UploadFile = File(...),
    scan_only: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """Upload and ingest a SIHOS Excel export."""
    from app.services.billing import ingest
    from app.repositories.institution_repo import InstitutionRepo

    inst_repo = InstitutionRepo(db)
    institution = await inst_repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")

    file_bytes = await file.read()
    result = await ingest(file_bytes, institution, period_id, db, scan_only=scan_only)
    return result


@router.get("/export")
async def export_invoices(period_id: int, db: AsyncSession = Depends(get_db)):
    """Export all invoices for a period to Excel (.xlsx)."""
    import openpyxl

    repo = InvoiceRepo(db)
    invoices = await repo.get_all_for_export(period_id)

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Facturas")
    ws.append([
        "Período", "Hospital", "Factura", "Fecha",
        "Tipo Doc.", "Número Doc.", "Paciente",
        "Administradora", "Contrato", "Servicio",
        "Operación", "Estado", "Hallazgos",
    ])

    for inv in invoices:
        period_label = inv.period.period_label if inv.period else ""
        hospital = (
            inv.period.institution.display_name
            if inv.period and inv.period.institution else ""
        )
        admin = (
            inv.admin.canonical_admin or inv.admin.raw_admin
            if inv.admin else ""
        )
        contract = (
            inv.contract.canonical_contract or inv.contract.raw_contract
            if inv.contract else ""
        )
        service = inv.service_type.display_name if inv.service_type else ""
        status = inv.folder_status.status if inv.folder_status else ""
        findings = ", ".join(
            mf.doc_type.code
            for mf in inv.missing_files
            if mf.resolved_at is None and mf.doc_type
        )

        ws.append([
            period_label,
            hospital,
            inv.invoice_number,
            inv.date.isoformat() if inv.date else "",
            inv.id_type,
            inv.id_number,
            inv.patient_name,
            admin,
            contract,
            service,
            inv.employee or "",
            status,
            findings,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"facturas_{period_id}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
