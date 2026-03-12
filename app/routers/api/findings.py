"""API router for audit findings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.finding_repo import FindingRepo
from app.schemas.finding import FindingCreate, FindingOut

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("/{invoice_id}", response_model=list[FindingOut])
async def get_findings(invoice_id: int, db: AsyncSession = Depends(get_db)):
    repo = FindingRepo(db)
    return await repo.get_findings_for_invoice(invoice_id)


@router.post("", response_model=FindingOut, status_code=201)
async def record_finding(data: FindingCreate, db: AsyncSession = Depends(get_db)):
    repo = FindingRepo(db)
    finding = await repo.record_finding(data.invoice_id, data.doc_code, data.comment)
    await db.commit()
    return finding


@router.delete("/{invoice_id}/{doc_code}", status_code=204)
async def delete_finding(invoice_id: int, doc_code: str, db: AsyncSession = Depends(get_db)):
    repo = FindingRepo(db)
    await repo.delete_finding(invoice_id, doc_code)
    await db.commit()


@router.delete("/{invoice_id}", status_code=204)
async def delete_all_findings(invoice_id: int, db: AsyncSession = Depends(get_db)):
    repo = FindingRepo(db)
    await repo.delete_all_findings(invoice_id)
    await db.commit()
