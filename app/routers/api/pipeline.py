"""API router for pipeline stage execution via SSE."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.institution_repo import InstitutionRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.services import pipeline_runner

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/run/{stage}")
async def run_stage(
    stage: str,
    institution_id: int,
    period_id: int,
    invoice_numbers: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Stream SSE log lines from a pipeline stage.

    Optional query param ``invoice_numbers``: comma-separated list of invoice
    numbers, used by stages such as DOWNLOAD_INVOICES_FROM_SIHOS.
    """
    inst_repo = InstitutionRepo(db)
    institution = await inst_repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")

    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_period_by_id(period_id)
    if not period:
        raise HTTPException(404, "Período no encontrado")

    extra: dict = {}
    if invoice_numbers:
        extra["invoice_numbers"] = [n.strip() for n in invoice_numbers.split(",") if n.strip()]

    async def event_gen():
        async for line in pipeline_runner.execute(stage, institution, period, db, extra):
            payload = json.dumps({"msg": line})
            yield f"data: {payload}\n\n"
        yield "data: {\"msg\": \"[DONE]\"}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
