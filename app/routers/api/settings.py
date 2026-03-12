"""API router for business rules settings (service types, doc types, folder statuses, mappings)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.hospital_repo import HospitalRepo
from app.repositories.rules_repo import RulesRepo
from app.schemas.hospital import AdminOut, AdminUpdate, ContractOut, ContractUpdate
from app.schemas.rules import DocTypeOut, DocTypeUpdate, FolderStatusDefOut, ServiceTypeOut, ServiceTypeUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


# ------------------------------------------------------------------
# Service types
# ------------------------------------------------------------------

@router.get("/service-types", response_model=list[ServiceTypeOut])
async def list_service_types(db: AsyncSession = Depends(get_db)):
    return await RulesRepo(db).get_service_types()


@router.patch("/service-types/{service_type_id}", response_model=ServiceTypeOut)
async def update_service_type(
    service_type_id: int, data: ServiceTypeUpdate, db: AsyncSession = Depends(get_db)
):
    repo = RulesRepo(db)
    obj = await repo.update_service_type(
        service_type_id, {k: v for k, v in data.model_dump().items() if v is not None}
    )
    if not obj:
        raise HTTPException(404, "Tipo de servicio no encontrado")
    await db.commit()
    return obj


# ------------------------------------------------------------------
# Doc types
# ------------------------------------------------------------------

@router.get("/doc-types", response_model=list[DocTypeOut])
async def list_doc_types(db: AsyncSession = Depends(get_db)):
    return await RulesRepo(db).get_doc_types()


@router.patch("/doc-types/{doc_type_id}", response_model=DocTypeOut)
async def update_doc_type(
    doc_type_id: int, data: DocTypeUpdate, db: AsyncSession = Depends(get_db)
):
    repo = RulesRepo(db)
    obj = await repo.update_doc_type(
        doc_type_id, {k: v for k, v in data.model_dump().items() if v is not None}
    )
    if not obj:
        raise HTTPException(404, "Tipo de documento no encontrado")
    await db.commit()
    return obj


# ------------------------------------------------------------------
# Folder statuses
# ------------------------------------------------------------------

@router.get("/folder-statuses", response_model=list[FolderStatusDefOut])
async def list_folder_statuses(db: AsyncSession = Depends(get_db)):
    return await RulesRepo(db).get_folder_statuses()


# ------------------------------------------------------------------
# Admin / contract mappings
# ------------------------------------------------------------------

@router.get("/mappings/{hospital_key}/admins", response_model=list[AdminOut])
async def pending_admins(hospital_key: str, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(hospital_key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    return await repo.get_pending_admins(hospital.id)


@router.patch("/mappings/admins/{admin_id}", response_model=AdminOut)
async def map_admin(admin_id: int, data: AdminUpdate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    await repo.set_admin_canonical(admin_id, data.canonical_value)
    await db.commit()
    from app.models.hospital import Admin
    return await db.get(Admin, admin_id)


@router.get("/mappings/{hospital_key}/contracts", response_model=list[ContractOut])
async def pending_contracts(hospital_key: str, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    hospital = await repo.get_by_key(hospital_key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")
    return await repo.get_pending_contracts(hospital.id)


@router.patch("/mappings/contracts/{contract_id}", response_model=ContractOut)
async def map_contract(contract_id: int, data: ContractUpdate, db: AsyncSession = Depends(get_db)):
    repo = HospitalRepo(db)
    await repo.set_contract_canonical(contract_id, data.canonical_value)
    await db.commit()
    from app.models.hospital import Contract
    return await db.get(Contract, contract_id)
