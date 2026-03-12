"""API router for hospitals CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.database import get_db
from app.repositories.hospital_repo import HospitalRepo
from app.schemas.hospital import (
    AdminOut, AdminUpdate, ContractOut, ContractUpdate,
    HospitalCreate, HospitalOut, HospitalUpdate,
)

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.get("", response_model=list[HospitalOut])
async def list_hospitals(db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    return await repo.get_all()


@router.post("", response_model=HospitalOut, status_code=201)
async def create_hospital(data: HospitalCreate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    obj = data.model_dump()
    # Encrypt secrets
    if obj.get("sihos_password"):
        obj["sihos_password_enc"] = crypto.encrypt(obj.pop("sihos_password"))
    else:
        obj.pop("sihos_password", None)
    if obj.get("drive_credentials_json"):
        obj["drive_credentials_json_enc"] = crypto.encrypt(obj.pop("drive_credentials_json"))
    else:
        obj.pop("drive_credentials_json", None)
    hospital = await repo.create(obj)
    await db.commit()
    return hospital


@router.get("/{key}", response_model=HospitalOut)
async def get_hospital(key: str, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    return hospital


@router.put("/{key}", response_model=HospitalOut)
async def update_hospital(key: str, data: HospitalUpdate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    obj = {k: v for k, v in data.model_dump().items() if v is not None}
    if "sihos_password" in obj:
        obj["sihos_password_enc"] = crypto.encrypt(obj.pop("sihos_password"))
    if "drive_credentials_json" in obj:
        obj["drive_credentials_json_enc"] = crypto.encrypt(obj.pop("drive_credentials_json"))
    updated = await repo.update(hospital.id, obj)
    await db.commit()
    return updated


# ------------------------------------------------------------------
# Admins sub-resource
# ------------------------------------------------------------------

@router.get("/{key}/admins", response_model=list[AdminOut])
async def list_admins(key: str, pending_only: bool = False, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    if pending_only:
        return await repo.get_pending_admins(hospital.id)
    return await repo.get_admins(hospital.id)


@router.patch("/admins/{admin_id}", response_model=AdminOut)
async def update_admin(admin_id: int, data: AdminUpdate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    await repo.set_admin_canonical(admin_id, data.canonical_value)
    await db.commit()
    admin = await db.get(__import__("app.models.hospital", fromlist=["Admin"]).Admin, admin_id)
    return admin


# ------------------------------------------------------------------
# Contracts sub-resource
# ------------------------------------------------------------------

@router.get("/{key}/contracts", response_model=list[ContractOut])
async def list_contracts(key: str, pending_only: bool = False, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    if pending_only:
        return await repo.get_pending_contracts(hospital.id)
    # Return all contracts for the hospital (via admins)
    admins = await repo.get_admins(hospital.id)
    contracts = []
    for admin in admins:
        contracts.extend(await repo.get_contracts(admin.id))
    return contracts


@router.patch("/contracts/{contract_id}", response_model=ContractOut)
async def update_contract(contract_id: int, data: ContractUpdate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    await repo.set_contract_canonical(contract_id, data.canonical_value)
    await db.commit()
    from app.models.hospital import Contract
    contract = await db.get(Contract, contract_id)
    return contract
