"""Async repository for business rules: service types, doc types, folder statuses."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rules import DocType, FolderStatus, ServiceType


class RulesRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Service types
    # ------------------------------------------------------------------

    async def get_service_types(self) -> list[ServiceType]:
        """Return all service types ordered by priority descending."""
        result = await self.db.execute(
            select(ServiceType).order_by(ServiceType.priority.desc(), ServiceType.code)
        )
        return list(result.scalars().all())

    async def get_service_type_by_code(self, code: str) -> ServiceType | None:
        result = await self.db.execute(select(ServiceType).where(ServiceType.code == code))
        return result.scalar_one_or_none()

    async def upsert_service_type(self, data: dict) -> ServiceType:
        stmt = (
            pg_insert(ServiceType)
            .values(**data)
            .on_conflict_do_update(index_elements=["code"], set_=data)
            .returning(ServiceType)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def update_service_type(self, service_type_id: int, data: dict) -> ServiceType | None:
        obj = await self.db.get(ServiceType, service_type_id)
        if not obj:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        return obj

    # ------------------------------------------------------------------
    # Doc types
    # ------------------------------------------------------------------

    async def get_doc_types(self) -> list[DocType]:
        result = await self.db.execute(select(DocType).order_by(DocType.code))
        return list(result.scalars().all())

    async def upsert_doc_type(self, data: dict) -> DocType:
        stmt = (
            pg_insert(DocType)
            .values(**data)
            .on_conflict_do_update(index_elements=["code"], set_=data)
            .returning(DocType)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def update_doc_type(self, doc_type_id: int, data: dict) -> DocType | None:
        obj = await self.db.get(DocType, doc_type_id)
        if not obj:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        await self.db.flush()
        return obj

    # ------------------------------------------------------------------
    # Folder statuses
    # ------------------------------------------------------------------

    async def get_folder_statuses(self) -> list[FolderStatus]:
        result = await self.db.execute(select(FolderStatus).order_by(FolderStatus.id))
        return list(result.scalars().all())

    async def get_folder_status_by_status(self, status: str) -> FolderStatus | None:
        result = await self.db.execute(
            select(FolderStatus).where(FolderStatus.status == status)
        )
        return result.scalar_one_or_none()
