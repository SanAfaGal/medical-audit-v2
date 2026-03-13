"""Async repository for invoices and audit periods."""
from __future__ import annotations

import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.period import AuditPeriod


class InvoiceRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Periods
    # ------------------------------------------------------------------

    async def get_periods(self, institution_id: int) -> list[AuditPeriod]:
        result = await self.db.execute(
            select(AuditPeriod)
            .where(AuditPeriod.institution_id == institution_id)
            .order_by(AuditPeriod.date_from.desc())
        )
        return list(result.scalars().all())

    async def get_or_create_period(
        self,
        institution_id: int,
        date_from: datetime.date,
        date_to: datetime.date,
        period_label: str,
    ) -> AuditPeriod:
        stmt = (
            pg_insert(AuditPeriod)
            .values(
                institution_id=institution_id,
                date_from=date_from,
                date_to=date_to,
                period_label=period_label,
            )
            .on_conflict_do_nothing(
                index_elements=["institution_id", "date_from", "date_to", "period_label"]
            )
            .returning(AuditPeriod)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(AuditPeriod).where(
                    AuditPeriod.institution_id == institution_id,
                    AuditPeriod.date_from == date_from,
                    AuditPeriod.date_to == date_to,
                    AuditPeriod.period_label == period_label,
                )
            )
            row = result2.scalar_one()
        return row

    async def get_period_by_id(self, period_id: int) -> AuditPeriod | None:
        return await self.db.get(AuditPeriod, period_id)

    async def delete_period(self, period_id: int) -> None:
        """Delete a period and cascade-delete all invoices and missing files."""
        period = await self.db.get(AuditPeriod, period_id)
        if period:
            await self.db.delete(period)
            await self.db.flush()

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    async def get_by_id(self, invoice_id: int) -> Invoice | None:
        return await self.db.get(Invoice, invoice_id)

    async def upsert_invoice(
        self, audit_period_id: int, invoice_number: str, data: dict
    ) -> Invoice:
        """Insert invoice; on conflict do nothing (preserve existing missing files)."""
        stmt = (
            pg_insert(Invoice)
            .values(audit_period_id=audit_period_id, invoice_number=invoice_number, **data)
            .on_conflict_do_nothing(index_elements=["audit_period_id", "invoice_number"])
            .returning(Invoice)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Invoice).where(
                    Invoice.audit_period_id == audit_period_id,
                    Invoice.invoice_number == invoice_number,
                )
            )
            row = result2.scalar_one()
        return row

    async def filter_invoices(
        self,
        audit_period_id: int,
        folder_status_id: int | None = None,
        service_type_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Invoice], int]:
        """Return paginated invoices with eager-loaded FK relationships, plus total count."""
        q = select(Invoice).where(Invoice.audit_period_id == audit_period_id)

        if folder_status_id is not None:
            q = q.where(Invoice.folder_status_id == folder_status_id)
        if service_type_id is not None:
            q = q.where(Invoice.service_type_id == service_type_id)
        if search:
            pattern = f"%{search.upper()}%"
            q = q.where(
                Invoice.invoice_number.ilike(pattern)
                | Invoice.patient_name.ilike(pattern)
            )

        count_q = select(func.count()).select_from(q.subquery())
        total_result = await self.db.execute(count_q)
        total = total_result.scalar_one()

        q = (
            q.order_by(Invoice.invoice_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(
                selectinload(Invoice.folder_status),
                selectinload(Invoice.service_type),
                selectinload(Invoice.admin),
                selectinload(Invoice.missing_files),
            )
        )
        result = await self.db.execute(q)
        return list(result.scalars().all()), total

    async def update_folder_status(self, invoice_id: int, folder_status_id: int) -> None:
        await self.db.execute(
            update(Invoice).where(Invoice.id == invoice_id).values(folder_status_id=folder_status_id)
        )
        await self.db.flush()

    async def batch_update_status(self, invoice_ids: list[int], folder_status_id: int) -> None:
        await self.db.execute(
            update(Invoice)
            .where(Invoice.id.in_(invoice_ids))
            .values(folder_status_id=folder_status_id)
        )
        await self.db.flush()

    async def delete_invoice(self, invoice_id: int) -> bool:
        invoice = await self.db.get(Invoice, invoice_id)
        if not invoice:
            return False
        await self.db.delete(invoice)
        await self.db.flush()
        return True
