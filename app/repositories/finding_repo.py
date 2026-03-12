"""Async repository for audit findings (missing documents)."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding
from app.models.invoice import Invoice


class FindingRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_finding(
        self, invoice_id: int, doc_code: str, comment: str = ""
    ) -> Finding:
        """Insert finding; no-op if already exists."""
        stmt = (
            pg_insert(Finding)
            .values(invoice_id=invoice_id, doc_code=doc_code, comment=comment)
            .on_conflict_do_nothing(index_elements=["invoice_id", "doc_code"])
            .returning(Finding)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            result2 = await self.db.execute(
                select(Finding).where(
                    Finding.invoice_id == invoice_id, Finding.doc_code == doc_code
                )
            )
            row = result2.scalar_one()
        return row

    async def delete_finding(self, invoice_id: int, doc_code: str) -> None:
        await self.db.execute(
            delete(Finding).where(
                Finding.invoice_id == invoice_id, Finding.doc_code == doc_code
            )
        )
        await self.db.flush()

    async def get_findings_for_invoice(self, invoice_id: int) -> list[Finding]:
        result = await self.db.execute(
            select(Finding).where(Finding.invoice_id == invoice_id).order_by(Finding.doc_code)
        )
        return list(result.scalars().all())

    async def get_findings_grouped(self, period_id: int) -> dict[str, list[str]]:
        """Return {factura: [doc_codes]} for all invoices in a period."""
        result = await self.db.execute(
            select(Invoice.factura, Finding.doc_code)
            .join(Finding, Finding.invoice_id == Invoice.id)
            .where(Invoice.period_id == period_id)
            .order_by(Invoice.factura, Finding.doc_code)
        )
        grouped: dict[str, list[str]] = defaultdict(list)
        for factura, doc_code in result.all():
            grouped[factura].append(doc_code)
        return dict(grouped)

    async def delete_all_findings(self, invoice_id: int) -> None:
        await self.db.execute(delete(Finding).where(Finding.invoice_id == invoice_id))
        await self.db.flush()
