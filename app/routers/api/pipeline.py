"""API router for pipeline stage execution via SSE."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.hospital_repo import HospitalRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.services import pipeline_runner

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/run/{stage}")
async def run_stage(
    stage: str,
    hospital_key: str,
    period_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Stream SSE log lines from a pipeline stage.

    The client connects with HTMX sse-connect; each event is a JSON object
    ``{"msg": "...log line..."}`` on the ``message`` event channel.
    """
    hosp_repo = HospitalRepo(db)
    hospital = await hosp_repo.get_by_key(hospital_key)
    if not hospital:
        raise HTTPException(404, "Hospital no encontrado")

    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_or_create_period(hospital.id, period_code)
    await db.commit()

    async def event_gen():
        async for line in pipeline_runner.execute(stage, hospital, period, db):
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
