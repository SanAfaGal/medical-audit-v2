"""Router para el explorador de archivos PDF integrado en la UI."""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.institution import Institution
from app.models.period import AuditPeriod
from app.models.rules import SystemSettings
from app.schemas.explorer import (
    FileNode,
    ListResponse,
    MergeRequest,
    MoveRequest,
    OperationResult,
    ReorderRequest,
    RenameRequest,
    SplitRequest,
)

router = APIRouter(prefix="/explorer", tags=["explorer"])


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de seguridad (sandbox)
# ──────────────────────────────────────────────────────────────────────────────

async def _resolve_sandbox(institution_id: int, period_id: int, db: AsyncSession) -> Path:
    """Devuelve la ruta sandbox: audit_data_root / institution.name / period.period_label."""
    # Obtener audit_data_root
    result = await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings or not settings.audit_data_root:
        raise HTTPException(400, "La ruta raíz de datos de auditoría no está configurada")

    # Obtener institución
    result = await db.execute(select(Institution).where(Institution.id == institution_id))
    institution = result.scalar_one_or_none()
    if not institution:
        raise HTTPException(404, "Institución no encontrada")

    # Obtener período
    result = await db.execute(
        select(AuditPeriod).where(
            AuditPeriod.id == period_id,
            AuditPeriod.institution_id == institution_id,
        )
    )
    period = result.scalar_one_or_none()
    if not period:
        raise HTTPException(404, "Período no encontrado")

    sandbox = (Path(settings.audit_data_root) / institution.name / period.period_label).resolve()
    return sandbox


def _safe_resolve(sandbox: Path, rel: str) -> Path:
    """Resuelve una ruta relativa dentro del sandbox. Lanza 400 si escapa del sandbox."""
    try:
        resolved = (sandbox / rel.lstrip("/\\")).resolve()
        resolved.relative_to(sandbox)  # lanza ValueError si escapa
        return resolved
    except ValueError:
        raise HTTPException(400, "Ruta fuera del directorio permitido")


# ──────────────────────────────────────────────────────────────────────────────
# Listar directorio
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/list", response_model=ListResponse)
async def list_directory(
    institution_id: int = Query(...),
    period_id: int = Query(...),
    root: str = Query("DRIVE"),
    path: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Lista carpetas y archivos PDF en el directorio indicado."""
    sandbox = await _resolve_sandbox(institution_id, period_id, db)

    rel = f"{root}/{path}".strip("/")
    target = _safe_resolve(sandbox, rel)

    if not target.exists():
        return ListResponse(entries=[], current_path=rel)
    if not target.is_dir():
        raise HTTPException(400, "La ruta no es un directorio")

    entries: list[FileNode] = []
    try:
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.is_dir():
                entries.append(FileNode(
                    name=item.name,
                    path=str(item.relative_to(sandbox)).replace("\\", "/"),
                    is_dir=True,
                ))
            elif item.suffix.lower() == ".pdf":
                entries.append(FileNode(
                    name=item.name,
                    path=str(item.relative_to(sandbox)).replace("\\", "/"),
                    is_dir=False,
                    size=item.stat().st_size,
                ))
    except PermissionError as e:
        raise HTTPException(403, f"Sin permiso para leer el directorio: {e}")

    return ListResponse(entries=entries, current_path=rel)


# ──────────────────────────────────────────────────────────────────────────────
# Servir PDF
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/file")
async def serve_file(
    institution_id: int = Query(...),
    period_id: int = Query(...),
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Sirve el PDF como StreamingResponse para previsualización."""
    sandbox = await _resolve_sandbox(institution_id, period_id, db)
    target = _safe_resolve(sandbox, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    if target.suffix.lower() != ".pdf":
        raise HTTPException(400, "Solo se pueden servir archivos PDF")

    async def _iter():
        async with aiofiles.open(target, "rb") as f:
            while chunk := await f.read(65536):
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{target.name}"'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Miniaturas
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/thumbnails")
async def get_thumbnails(
    institution_id: int = Query(...),
    period_id: int = Query(...),
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Renderiza cada página como PNG base64 para la UI de reordenamiento."""
    sandbox = await _resolve_sandbox(institution_id, period_id, db)
    target = _safe_resolve(sandbox, path)

    if not target.exists() or target.suffix.lower() != ".pdf":
        raise HTTPException(404, "Archivo PDF no encontrado")

    def _render() -> list[str]:
        import fitz  # PyMuPDF
        doc = fitz.open(str(target))
        result = []
        matrix = fitz.Matrix(0.5, 0.5)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            png_bytes = pix.tobytes("png")
            result.append(base64.b64encode(png_bytes).decode())
        doc.close()
        return result

    thumbnails = await asyncio.get_event_loop().run_in_executor(None, _render)
    return {"thumbnails": thumbnails, "count": len(thumbnails)}


# ──────────────────────────────────────────────────────────────────────────────
# Renombrar
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/rename", response_model=OperationResult)
async def rename_entry(body: RenameRequest, db: AsyncSession = Depends(get_db)):
    """Renombra un archivo o carpeta."""
    sandbox = await _resolve_sandbox(body.institution_id, body.period_id, db)
    src = _safe_resolve(sandbox, body.path)

    if not src.exists():
        raise HTTPException(404, "Archivo o carpeta no encontrado")

    # Validar que new_name no contenga separadores de ruta
    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(400, "El nuevo nombre no puede contener separadores de ruta")

    dst = src.parent / body.new_name
    _safe_resolve(sandbox, str(dst.relative_to(sandbox)))  # verificar sandbox

    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(500, f"Error al renombrar: {e}")

    return OperationResult(ok=True, message=f"Renombrado a {body.new_name}")


# ──────────────────────────────────────────────────────────────────────────────
# Mover
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/move", response_model=OperationResult)
async def move_entry(body: MoveRequest, db: AsyncSession = Depends(get_db)):
    """Mueve un archivo o carpeta a otra carpeta destino."""
    sandbox = await _resolve_sandbox(body.institution_id, body.period_id, db)
    src = _safe_resolve(sandbox, body.src)
    dst_folder = _safe_resolve(sandbox, body.dst_folder)

    if not src.exists():
        raise HTTPException(404, "Origen no encontrado")
    if not dst_folder.is_dir():
        raise HTTPException(400, "Destino no es un directorio")

    dst = dst_folder / src.name
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(500, f"Error al mover: {e}")

    return OperationResult(ok=True, message=f"Movido a {dst_folder.name}/{src.name}")


# ──────────────────────────────────────────────────────────────────────────────
# Unir PDFs (merge)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/merge", response_model=OperationResult)
async def merge_pdfs(body: MergeRequest, db: AsyncSession = Depends(get_db)):
    """Une múltiples PDFs en uno solo."""
    sandbox = await _resolve_sandbox(body.institution_id, body.period_id, db)

    if len(body.paths) < 2:
        raise HTTPException(400, "Se necesitan al menos 2 PDFs para unir")

    resolved_paths = [_safe_resolve(sandbox, p) for p in body.paths]
    for p in resolved_paths:
        if not p.exists() or p.suffix.lower() != ".pdf":
            raise HTTPException(404, f"PDF no encontrado: {p.name}")

    # Carpeta de salida: la del primer PDF
    output_name = body.output_name if body.output_name.endswith(".pdf") else body.output_name + ".pdf"
    output_path = resolved_paths[0].parent / output_name
    _safe_resolve(sandbox, str(output_path.relative_to(sandbox)))  # verificar sandbox

    def _merge():
        import fitz
        merged = fitz.open()
        for p in resolved_paths:
            doc = fitz.open(str(p))
            merged.insert_pdf(doc)
            doc.close()
        merged.save(str(output_path))
        merged.close()

    await asyncio.get_event_loop().run_in_executor(None, _merge)
    return OperationResult(ok=True, message=f"PDFs unidos en {output_name}")


# ──────────────────────────────────────────────────────────────────────────────
# Dividir PDF (split)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_ranges(ranges_str: str, total_pages: int) -> list[list[int]]:
    """Parsea un string de rangos como '1-3, 5' (1-based) a listas de índices 0-based."""
    groups: list[list[int]] = []
    for token in ranges_str.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-")
            start = int(parts[0].strip()) - 1
            end = int(parts[1].strip()) - 1
            groups.append(list(range(max(0, start), min(total_pages - 1, end) + 1)))
        else:
            idx = int(token) - 1
            if 0 <= idx < total_pages:
                groups.append([idx])
    return groups


@router.post("/split", response_model=OperationResult)
async def split_pdf(body: SplitRequest, db: AsyncSession = Depends(get_db)):
    """Divide un PDF por rangos o página a página."""
    sandbox = await _resolve_sandbox(body.institution_id, body.period_id, db)
    src = _safe_resolve(sandbox, body.path)

    if not src.exists() or src.suffix.lower() != ".pdf":
        raise HTTPException(404, "PDF no encontrado")

    def _split():
        import fitz
        doc = fitz.open(str(src))
        total = doc.page_count
        stem = src.stem

        if body.ranges:
            groups = _parse_ranges(body.ranges, total)
        else:
            groups = [[i] for i in range(total)]

        output_dir = src.parent
        created = 0
        for i, pages in enumerate(groups, start=1):
            sub = fitz.open()
            sub.insert_pdf(doc, from_page=pages[0], to_page=pages[-1])
            # Para rangos no contiguos, insertar página por página
            if len(pages) > 1 and pages != list(range(pages[0], pages[-1] + 1)):
                sub = fitz.open()
                for pg in pages:
                    sub.insert_pdf(doc, from_page=pg, to_page=pg)
            out_name = f"{stem}_parte{i:03d}.pdf"
            sub.save(str(output_dir / out_name))
            sub.close()
            created += 1
        doc.close()
        return created

    n = await asyncio.get_event_loop().run_in_executor(None, _split)
    return OperationResult(ok=True, message=f"PDF dividido en {n} archivo(s)")


# ──────────────────────────────────────────────────────────────────────────────
# Reordenar páginas
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/reorder", response_model=OperationResult)
async def reorder_pages(body: ReorderRequest, db: AsyncSession = Depends(get_db)):
    """Reordena las páginas de un PDF (modifica el archivo in-place)."""
    sandbox = await _resolve_sandbox(body.institution_id, body.period_id, db)
    src = _safe_resolve(sandbox, body.path)

    if not src.exists() or src.suffix.lower() != ".pdf":
        raise HTTPException(404, "PDF no encontrado")

    def _reorder():
        import fitz
        doc = fitz.open(str(src))
        if len(body.page_order) != doc.page_count:
            doc.close()
            raise ValueError(f"page_order tiene {len(body.page_order)} elementos pero el PDF tiene {doc.page_count} páginas")
        doc.select(body.page_order)
        doc.save(str(src), incremental=False)
        doc.close()

    try:
        await asyncio.get_event_loop().run_in_executor(None, _reorder)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return OperationResult(ok=True, message="Páginas reordenadas correctamente")


# ──────────────────────────────────────────────────────────────────────────────
# Ocultar consola Windows
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/console-hide", response_model=OperationResult)
async def console_hide():
    """Oculta la ventana de consola de Windows."""
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
        return OperationResult(ok=True, message="Consola ocultada")
    except Exception as e:
        return OperationResult(ok=False, message=f"No se pudo ocultar la consola: {e}")
