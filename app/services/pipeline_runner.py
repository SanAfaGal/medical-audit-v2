"""Pipeline runner: async generator that executes stages and yields log lines."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Institution
from app.models.period import AuditPeriod

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------

_STAGE_HANDLERS: dict[str, "_StageHandler"] = {}


def _stage(name: str):
    """Decorator to register a stage handler."""
    def decorator(fn):
        _STAGE_HANDLERS[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

_StageHandler = "async def f(ctx: dict) -> AsyncGenerator[str, None]"


# ---------------------------------------------------------------------------
# Helper: emit log lines from a stdlib logger
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    """Logging handler that puts formatted records into an asyncio Queue."""

    def __init__(self, queue: asyncio.Queue) -> None:
        super().__init__()
        self.queue = queue
        self.setFormatter(logging.Formatter("%(levelname)-8s %(name)s — %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(self.format(record))
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(institution: Institution, period: AuditPeriod, db: AsyncSession, extra: dict) -> dict:
    base = Path(institution.base_path or "") / period.period_label
    return {
        "institution": institution,
        "period":      period,
        "db":          db,
        "base_path":   base,
        "drive_path":  base / "DRIVE",
        "stage_path":  base / "STAGE",
        "audit_path":  base / "AUDIT",
        **extra,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def execute(
    stage: str,
    institution: Institution,
    period: AuditPeriod,
    db: AsyncSession,
    extra: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Yield log lines as a pipeline stage executes.

    Usage (SSE endpoint)::

        async for line in pipeline_runner.execute(stage, institution, period, db):
            yield f"data: {json.dumps({'msg': line})}\n\n"
    """
    ctx = _build_context(institution, period, db, extra or {})
    handler_fn = _STAGE_HANDLERS.get(stage)

    if handler_fn is None:
        yield f"[ERROR] Etapa desconocida: {stage}"
        return

    yield f"[INFO] Iniciando etapa: {stage}"
    try:
        async for line in handler_fn(ctx):
            yield line
        yield f"[INFO] Etapa completada: {stage}"
    except Exception as exc:
        logger.exception("Pipeline stage %s failed", stage)
        yield f"[ERROR] {stage} falló: {exc}"


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

@_stage("LOAD_AND_PROCESS")
async def _load_and_process(ctx: dict) -> AsyncGenerator[str, None]:
    """Load SIHOS Excel and upsert invoices. Requires ctx['file_bytes'] and ctx['period_code']."""
    from app.services.billing import ingest

    file_bytes: bytes | None = ctx.get("file_bytes")
    period_code: str | None = ctx.get("period_code")

    if not file_bytes:
        yield "[ERROR] No se proporcionó el archivo Excel de SIHOS."
        return
    if not period_code:
        yield "[ERROR] No se especificó el período."
        return

    yield "[INFO] Leyendo Excel SIHOS..."
    result = await ingest(file_bytes, ctx["hospital"], period_code, ctx["db"])
    yield f"[INFO] Insertadas: {result['inserted']} facturas"
    if result["skipped"]:
        yield f"[WARN] Omitidas (admin sin mapear): {result['skipped']}"
    for admin in result["unknown_admins"]:
        yield f"[WARN] Administradora sin mapear: {admin}"
    for contract in result["unknown_contracts"]:
        yield f"[WARN] Contrato sin mapear: {contract}"


def _stub_stage(label: str):
    async def _handler(ctx: dict) -> AsyncGenerator[str, None]:
        yield f"[INFO] Etapa '{label}' aún no implementada en esta versión."
    return _handler


for _name, _label in [
    ("RUN_STAGING",                   "Mover carpetas BASE→STAGE"),
    ("REMOVE_NON_PDF",                "Eliminar archivos no PDF"),
    ("CHECK_INVALID_FILES",           "Detectar PDFs corruptos"),
    ("NORMALIZE_FILES",               "Renombrar archivos inválidos"),
    ("LIST_UNREADABLE_PDFS",          "Listar facturas sin texto"),
    ("DELETE_UNREADABLE_PDFS",        "Eliminar facturas sin texto"),
    ("DOWNLOAD_INVOICES_FROM_SIHOS",  "Descargar facturas SIHOS"),
    ("CHECK_INVOICES",                "Aplicar OCR"),
    ("VERIFY_INVOICE_CODE",           "Verificar número en PDF"),
    ("CHECK_INVOICE_NUMBER_ON_FILES", "Verificar número en archivos"),
    ("CHECK_FOLDERS_WITH_EXTRA_TEXT", "Detectar carpetas con texto extra"),
    ("NORMALIZE_DIR_NAMES",           "Renombrar carpetas malformadas"),
    ("CHECK_DIRS",                    "Detectar directorios faltantes"),
    ("CATEGORIZE_INVOICES",           "Categorizar facturas por tipo"),
    ("CHECK_REQUIRED_DOCS",           "Verificar documentos requeridos"),
    ("VERIFY_CUFE",                   "Verificar CUFE"),
    ("TAG_MISSING_CUFE",              "Marcar carpetas sin CUFE"),
    ("ORGANIZE",                      "Organizar carpetas"),
    ("DOWNLOAD_DRIVE",                "Descargar desde Drive"),
    ("DOWNLOAD_MISSING_DOCS",         "Descargar documentos faltantes"),
]:
    _STAGE_HANDLERS[_name] = _stub_stage(_label)
