"""API router for institutions CRUD (mounted at /api/institutions)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.database import get_db
from app.models.institution import Admin, Contract, Service
from app.repositories.institution_repo import InstitutionRepo
from app.schemas.institution import (
    AdminOut,
    AdminUpdate,
    ContractOut,
    ContractUpdate,
    InstitutionCreate,
    InstitutionOut,
    InstitutionUpdate,
    ServiceOut,
    ServiceUpdate,
)
from app.schemas.rules import ServiceTypeDocumentOut, ServiceTypeDocumentCreate

router = APIRouter(prefix="/institutions", tags=["institutions"])


def _encrypt_sensitive(data: dict) -> dict:
    """Encrypt sihos_password and drive_credentials_json in-place, return cleaned dict."""
    out = dict(data)
    if out.get("sihos_password"):
        out["sihos_password"] = crypto.encrypt(out["sihos_password"])
    else:
        out.pop("sihos_password", None)
    if out.get("drive_credentials_json"):
        out["drive_credentials_enc"] = crypto.encrypt(out.pop("drive_credentials_json"))
    else:
        out.pop("drive_credentials_json", None)
    return out


# ------------------------------------------------------------------
# Institutions
# ------------------------------------------------------------------

@router.get("", response_model=list[InstitutionOut])
async def list_institutions(db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    return await repo.get_all()


@router.post("", response_model=InstitutionOut, status_code=201)
async def create_institution(data: InstitutionCreate, db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    obj = _encrypt_sensitive(data.model_dump())
    institution = await repo.create(obj)
    await db.commit()
    return institution


@router.get("/{institution_id}", response_model=InstitutionOut)
async def get_institution(institution_id: int, db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    return institution


@router.put("/{institution_id}", response_model=InstitutionOut)
async def update_institution(
    institution_id: int, data: InstitutionUpdate, db: AsyncSession = Depends(get_db)
):
    repo = InstitutionRepo(db)
    obj = _encrypt_sensitive({k: v for k, v in data.model_dump().items() if v is not None})
    updated = await repo.update(institution_id, obj)
    if not updated:
        raise HTTPException(404, "Institución no encontrada")
    await db.commit()
    return updated


# ------------------------------------------------------------------
# Admins sub-resource
# ------------------------------------------------------------------

@router.get("/{institution_id}/admins", response_model=list[AdminOut])
async def list_admins(
    institution_id: int, pending_only: bool = False, db: AsyncSession = Depends(get_db)
):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    if pending_only:
        return await repo.get_pending_admins(institution_id)
    return await repo.get_admins(institution_id)


@router.patch("/admins/{admin_id}", response_model=AdminOut)
async def update_admin(admin_id: int, data: AdminUpdate, db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    await repo.set_admin_canonical(admin_id, data.canonical_admin, data.type)
    await db.commit()
    admin = await db.get(Admin, admin_id)
    if not admin:
        raise HTTPException(404, "Administradora no encontrada")
    return admin


# ------------------------------------------------------------------
# Contracts sub-resource
# ------------------------------------------------------------------

@router.get("/{institution_id}/contracts", response_model=list[ContractOut])
async def list_contracts(
    institution_id: int, pending_only: bool = False, db: AsyncSession = Depends(get_db)
):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    if pending_only:
        return await repo.get_pending_contracts(institution_id)
    return await repo.get_contracts(institution_id)


@router.patch("/contracts/{contract_id}", response_model=ContractOut)
async def update_contract(
    contract_id: int, data: ContractUpdate, db: AsyncSession = Depends(get_db)
):
    repo = InstitutionRepo(db)
    await repo.set_contract_canonical(contract_id, data.canonical_contract)
    await db.commit()
    contract = await db.get(Contract, contract_id)
    if not contract:
        raise HTTPException(404, "Contrato no encontrado")
    return contract


# ------------------------------------------------------------------
# Services sub-resource
# ------------------------------------------------------------------

@router.get("/{institution_id}/services", response_model=list[ServiceOut])
async def list_services(institution_id: int, db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    return await repo.get_services(institution_id)


@router.patch("/services/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: int, data: ServiceUpdate, db: AsyncSession = Depends(get_db)
):
    repo = InstitutionRepo(db)
    await repo.set_service_type(service_id, data.service_type_id)
    await db.commit()
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(404, "Servicio no encontrado")
    return service


# ------------------------------------------------------------------
# ServiceTypeDocuments sub-resource
# ------------------------------------------------------------------

@router.get("/{institution_id}/service-type-documents", response_model=list[ServiceTypeDocumentOut])
async def list_service_type_documents(institution_id: int, db: AsyncSession = Depends(get_db)):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    return await repo.get_service_type_documents(institution_id)


@router.post(
    "/{institution_id}/service-type-documents",
    response_model=ServiceTypeDocumentOut,
    status_code=201,
)
async def create_service_type_document(
    institution_id: int,
    data: ServiceTypeDocumentCreate,
    db: AsyncSession = Depends(get_db),
):
    repo = InstitutionRepo(db)
    institution = await repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")
    obj = await repo.upsert_service_type_document(
        institution_id, data.service_type_id, data.doc_type_id
    )
    await db.commit()
    return obj


@router.delete(
    "/{institution_id}/service-type-documents/{service_type_id}/{doc_type_id}",
    status_code=204,
)
async def delete_service_type_document(
    institution_id: int,
    service_type_id: int,
    doc_type_id: int,
    db: AsyncSession = Depends(get_db),
):
    repo = InstitutionRepo(db)
    await repo.delete_service_type_document(institution_id, service_type_id, doc_type_id)
    await db.commit()
