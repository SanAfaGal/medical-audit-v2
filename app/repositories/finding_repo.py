"""Async repository for missing files (audit findings)."""
from __future__ import annotations

import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import MissingFile


class MissingFileRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_missing_file(
        self, invoice_id: int, doc_type_id: int, expected_path: str
    ) -> MissingFile:
        """Insert missing file record; no-op if already exists (INSERT OR IGNORE)."""
        stmt = (
            pg_insert(MissingFile)
            .values(
                invoice_id=invoice_id,
                doc_type_id=doc_type_id,
                expected_path=expected_path,
            )
            .on_conflict_do_nothing(index_elements=["invoice_id", "doc_type_id"])
            .returning(MissingFile)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(MissingFile).where(
                    MissingFile.invoice_id == invoice_id,
                    MissingFile.doc_type_id == doc_type_id,
                )
            )
            row = result2.scalar_one()
        return row

    async def resolve_missing_file(self, invoice_id: int, doc_type_id: int) -> None:
        """Set resolved_at = now() for the given invoice+doc_type pair."""
        await self.db.execute(
            update(MissingFile)
            .where(
                MissingFile.invoice_id == invoice_id,
                MissingFile.doc_type_id == doc_type_id,
            )
            .values(resolved_at=datetime.datetime.utcnow())
        )
        await self.db.flush()

    async def delete_missing_file(self, invoice_id: int, doc_type_id: int) -> None:
        await self.db.execute(
            delete(MissingFile).where(
                MissingFile.invoice_id == invoice_id,
                MissingFile.doc_type_id == doc_type_id,
            )
        )
        await self.db.flush()

    async def get_for_invoice(self, invoice_id: int) -> list[MissingFile]:
        result = await self.db.execute(
            select(MissingFile)
            .where(MissingFile.invoice_id == invoice_id)
            .order_by(MissingFile.doc_type_id)
        )
        return list(result.scalars().all())

    async def delete_all_for_invoice(self, invoice_id: int) -> None:
        await self.db.execute(
            delete(MissingFile).where(MissingFile.invoice_id == invoice_id)
        )
        await self.db.flush()
