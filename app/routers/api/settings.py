"""API router for business rules settings (service types, doc types, folder statuses)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.rules_repo import RulesRepo
from app.schemas.rules import (
    DocTypeCreate,
    DocTypeOut,
    DocTypeUpdate,
    FolderStatusOut,
    ServiceTypeCreate,
    ServiceTypeOut,
    ServiceTypeUpdate,
)

router = APIRouter(prefix="/settings", tags=["settings"])


# ------------------------------------------------------------------
# Service types
# ------------------------------------------------------------------

@router.get("/service-types", response_model=list[ServiceTypeOut])
async def list_service_types(db: AsyncSession = Depends(get_db)):
    return await RulesRepo(db).get_service_types()


@router.post("/service-types", response_model=ServiceTypeOut, status_code=201)
async def create_service_type(data: ServiceTypeCreate, db: AsyncSession = Depends(get_db)):
    repo = RulesRepo(db)
    obj = await repo.upsert_service_type(data.model_dump())
    await db.commit()
    return obj


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


@router.post("/doc-types", response_model=DocTypeOut, status_code=201)
async def create_doc_type(data: DocTypeCreate, db: AsyncSession = Depends(get_db)):
    repo = RulesRepo(db)
    obj = await repo.upsert_doc_type(data.model_dump())
    await db.commit()
    return obj


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

@router.get("/folder-statuses", response_model=list[FolderStatusOut])
async def list_folder_statuses(db: AsyncSession = Depends(get_db)):
    return await RulesRepo(db).get_folder_statuses()
