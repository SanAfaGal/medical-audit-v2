"""API router for pipeline stage execution via SSE."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.paths import to_container_path
from app.repositories.institution_repo import InstitutionRepo
from app.repositories.invoice_repo import InvoiceRepo
from app.repositories.rules_repo import RulesRepo
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


@router.post("/load-drive-zip")
async def load_drive_zip(
    institution_id: int = Form(...),
    period_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Extract a .zip / .7z / .rar archive into the DRIVE folder of the given period."""
    inst_repo = InstitutionRepo(db)
    institution = await inst_repo.get_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institución no encontrada")

    inv_repo = InvoiceRepo(db)
    period = await inv_repo.get_period_by_id(period_id)
    if not period:
        raise HTTPException(404, "Período no encontrado")

    rules_repo = RulesRepo(db)
    sys_settings = await rules_repo.get_system_settings()
    if not sys_settings or not sys_settings.audit_data_root:
        raise HTTPException(500, "audit_data_root no configurado")

    drive_path: Path = (
        to_container_path(sys_settings.audit_data_root)
        / institution.name
        / period.period_label
        / "DRIVE"
    )
    drive_path.mkdir(parents=True, exist_ok=True)

    filename = file.filename or ""
    file_bytes = await file.read()
    ext = Path(filename).suffix.lower()

    extracted: list[str] = []

    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            members = [m for m in zf.infolist() if not m.filename.endswith("/")]
            for member in members:
                # Strip top-level directory if the archive has one
                parts = Path(member.filename).parts
                rel = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
                dest = drive_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member.filename))
                extracted.append(str(rel))

    elif ext == ".7z":
        try:
            import py7zr
        except ImportError:
            raise HTTPException(500, "py7zr no está instalado (soporte .7z no disponible)")
        with py7zr.SevenZipFile(io.BytesIO(file_bytes), mode="r") as szf:
            szf.extractall(path=str(drive_path))
            extracted = [str(p) for p in drive_path.rglob("*") if p.is_file()]

    elif ext == ".rar":
        import tempfile
        try:
            import rarfile
        except ImportError:
            raise HTTPException(500, "rarfile no está instalado (soporte .rar no disponible)")
        with tempfile.NamedTemporaryFile(suffix=".rar", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        with rarfile.RarFile(tmp_path) as rf:
            rf.extractall(path=str(drive_path))
        Path(tmp_path).unlink(missing_ok=True)
        extracted = [str(p) for p in drive_path.rglob("*") if p.is_file()]

    else:
        raise HTTPException(400, f"Formato no soportado: '{ext}'. Use .zip, .7z o .rar")

    return {
        "ok": True,
        "extracted": len(extracted),
        "drive_path": str(drive_path),
    }
