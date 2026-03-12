"""Async repository for invoices and audit periods."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.period import AuditPeriod


class InvoiceRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Periods
    # ------------------------------------------------------------------

    async def get_periods(self, hospital_id: int) -> list[AuditPeriod]:
        result = await self.db.execute(
            select(AuditPeriod)
            .where(AuditPeriod.hospital_id == hospital_id)
            .order_by(AuditPeriod.code.desc())
        )
        return list(result.scalars().all())

    async def get_or_create_period(self, hospital_id: int, code: str) -> AuditPeriod:
        stmt = (
            pg_insert(AuditPeriod)
            .values(hospital_id=hospital_id, code=code)
            .on_conflict_do_nothing(index_elements=["hospital_id", "code"])
            .returning(AuditPeriod)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(AuditPeriod).where(
                    AuditPeriod.hospital_id == hospital_id, AuditPeriod.code == code
                )
            )
            row = result2.scalar_one()
        return row

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    async def upsert_invoice(self, period_id: int, factura: str, data: dict) -> Invoice:
        """Insert invoice; on conflict do nothing (preserve existing findings)."""
        stmt = (
            pg_insert(Invoice)
            .values(period_id=period_id, factura=factura, **data)
            .on_conflict_do_nothing(index_elements=["period_id", "factura"])
            .returning(Invoice)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Invoice).where(
                    Invoice.period_id == period_id, Invoice.factura == factura
                )
            )
            row = result2.scalar_one()
        return row

    async def get_by_id(self, invoice_id: int) -> Invoice | None:
        return await self.db.get(Invoice, invoice_id)

    async def filter_invoices(
        self,
        period_id: int,
        folder_status: str | None = None,
        service_type_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Invoice], int]:
        """Return paginated invoices matching filters, plus total count."""
        q = select(Invoice).where(Invoice.period_id == period_id)

        if folder_status:
            q = q.where(Invoice.folder_status == folder_status)
        if service_type_id is not None:
            q = q.where(Invoice.service_type_id == service_type_id)
        if search:
            pattern = f"%{search.upper()}%"
            q = q.where(
                Invoice.factura.ilike(pattern)
                | Invoice.paciente.ilike(pattern)
                | Invoice.administradora.ilike(pattern)
            )

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await self.db.execute(count_q)
        total = total_result.scalar_one()

        q = q.order_by(Invoice.factura).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(q)
        return list(result.scalars().all()), total

    async def update_folder_status(self, invoice_id: int, status: str) -> None:
        await self.db.execute(
            update(Invoice).where(Invoice.id == invoice_id).values(folder_status=status)
        )
        await self.db.flush()

    async def batch_update_status(self, invoice_ids: list[int], status: str) -> None:
        await self.db.execute(
            update(Invoice).where(Invoice.id.in_(invoice_ids)).values(folder_status=status)
        )
        await self.db.flush()

    async def update_nota(self, invoice_id: int, nota: str) -> None:
        await self.db.execute(
            update(Invoice).where(Invoice.id == invoice_id).values(nota=nota)
        )
        await self.db.flush()

    async def set_service_type(self, invoice_id: int, service_type_id: int | None) -> None:
        await self.db.execute(
            update(Invoice).where(Invoice.id == invoice_id).values(service_type_id=service_type_id)
        )
        await self.db.flush()

    async def get_by_factura(self, period_id: int, factura: str) -> Invoice | None:
        result = await self.db.execute(
            select(Invoice).where(Invoice.period_id == period_id, Invoice.factura == factura)
        )
        return result.scalar_one_or_none()

    async def delete_period(self, hospital_id: int, period_code: str) -> None:
        """Delete a period and cascade-delete all invoices and findings."""
        result = await self.db.execute(
            select(AuditPeriod).where(
                AuditPeriod.hospital_id == hospital_id, AuditPeriod.code == period_code
            )
        )
        period = result.scalar_one_or_none()
        if period:
            await self.db.delete(period)
            await self.db.flush()
