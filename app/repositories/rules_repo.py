"""Async repository for business rules: service types, doc types, folder statuses."""
from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rules import DocType, FolderStatusDef, ServiceType


class RulesRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Service types
    # ------------------------------------------------------------------

    async def get_service_types(self, active_only: bool = False) -> list[ServiceType]:
        q = select(ServiceType).order_by(ServiceType.sort_order, ServiceType.code)
        if active_only:
            q = q.where(ServiceType.is_active.is_(True))
        result = await self.db.execute(q)
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

    async def get_doc_types(self, active_only: bool = False) -> list[DocType]:
        q = select(DocType).order_by(DocType.code)
        if active_only:
            q = q.where(DocType.is_active.is_(True))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_doc_type_prefixes(self) -> dict[str, list[str]]:
        """Return {code: [prefixes]} for all active doc types."""
        doc_types = await self.get_doc_types(active_only=True)
        return {dt.code: json.loads(dt.prefixes) for dt in doc_types}

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

    async def get_folder_statuses(self) -> list[FolderStatusDef]:
        result = await self.db.execute(
            select(FolderStatusDef).order_by(FolderStatusDef.sort_order)
        )
        return list(result.scalars().all())
