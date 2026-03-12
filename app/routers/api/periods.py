"""API router for audit periods."""
from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.hospital_repo import HospitalRepo
from app.repositories.invoice_repo import InvoiceRepo

router = APIRouter(prefix="/hospitals", tags=["periods"])


class PeriodOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    code: str


class PeriodCreate(BaseModel):
    code: str


@router.get("/{key}/periods", response_model=list[PeriodOut])
async def list_periods(key: str, db: AsyncSession = Depends(get_db)):
    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    inv_repo = InvoiceRepo(db)
    return await inv_repo.get_periods(hospital.id)


@router.post("/{key}/periods", response_model=PeriodOut, status_code=201)
async def create_period(key: str, data: PeriodCreate, db: AsyncSession = Depends(get_db)):
    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_or_create_period(hospital.id, data.code)
    await db.commit()
    return period


@router.delete("/{key}/periods/{code}", status_code=204)
async def delete_period(key: str, code: str, db: AsyncSession = Depends(get_db)):
    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    inv_repo = InvoiceRepo(db)
    await inv_repo.delete_period(hospital.id, code)
    await db.commit()
