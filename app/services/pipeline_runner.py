"""Pipeline runner: async generator that executes stages and yields log lines."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Institution
from app.models.period import AuditPeriod
from app.paths import to_container_path
from app.repositories.rules_repo import RulesRepo

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
# Context builder
# ---------------------------------------------------------------------------

def _build_context(institution: Institution, period: AuditPeriod, db: AsyncSession, extra: dict, audit_data_root: str) -> dict:
    base = to_container_path(audit_data_root) / institution.name / period.period_label
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
# Executor helper
# ---------------------------------------------------------------------------

def _get_executor():
    """Return a callable that runs a sync function in the default thread executor."""
    loop = asyncio.get_running_loop()

    async def run(fn, *args, **kwargs):
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    return run


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
    """Yield log lines as a pipeline stage executes."""
    sys_settings = await RulesRepo(db).get_system_settings()
    audit_data_root = sys_settings.audit_data_root if sys_settings and sys_settings.audit_data_root else ""
    if not audit_data_root:
        yield "[ERROR] audit_data_root no está configurado. Ve a Configuración → Sistema y define la ruta base."
        return
    ctx = _build_context(institution, period, db, extra or {}, audit_data_root)
    handler_fn = _STAGE_HANDLERS.get(stage)

    if handler_fn is None:
        yield f"[ERROR] Etapa desconocida: {stage}"
        return

    try:
        async for line in handler_fn(ctx):
            yield line
    except Exception as exc:
        logger.exception("Pipeline stage %s failed", stage)
        exc_desc = f"{type(exc).__name__}: {exc}" if str(exc).strip() else type(exc).__name__
        yield f"[ERROR] {stage} falló: {exc_desc}"


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

@_stage("LOAD_AND_PROCESS")
async def _load_and_process(ctx: dict) -> AsyncGenerator[str, None]:
    """Load SIHOS Excel and upsert invoices. Requires ctx['file_bytes'] and ctx['period_code']."""
    from app.services.billing import ingest

    file_bytes: bytes | None = ctx.get("file_bytes")

    if not file_bytes:
        yield "[ERROR] No se proporcionó el archivo Excel de SIHOS."
        return

    yield "[INFO] Leyendo Excel SIHOS..."
    result = await ingest(file_bytes, ctx["institution"], ctx["period"].id, ctx["db"])
    yield f"[INFO] Insertadas: {result['inserted']} facturas"
    if result["skipped"]:
        yield f"[WARN] Omitidas (admin sin mapear): {result['skipped']}"
    for admin in result["unknown_admins"]:
        yield f"[WARN] Administradora sin mapear: {admin}"
    for contract in result["unknown_contracts"]:
        yield f"[WARN] Contrato sin mapear: {contract}"
    for service in result["unknown_services"]:
        yield f"[WARN] Servicio sin reclasificar (GENERAL): {service}"

    # Guardar el Excel para permitir re-categorización posterior
    base_path: Path = ctx["base_path"]
    executor = _get_executor()
    def _save_excel(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    await executor(_save_excel, base_path / "sihos.xlsx", file_bytes)
    yield "[INFO] Excel guardado para futuras re-categorizaciones."


@_stage("RECATEGORIZE_SERVICES")
async def _recategorize_services(ctx: dict) -> AsyncGenerator[str, None]:
    """Re-apply current service mappings to all invoices in the period without reloading from SIHOS."""
    from app.repositories.institution_repo import InstitutionRepo
    from app.repositories.invoice_repo import InvoiceRepo
    from app.repositories.rules_repo import RulesRepo
    from app.services.billing import load_excel, _normalize

    base_path: Path = ctx["base_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db: AsyncSession = ctx["db"]

    excel_path = base_path / "sihos.xlsx"
    if not excel_path.exists():
        yield "[ERROR] No se encontró el Excel guardado. Ejecuta primero 'Cargar reporte SIHOS'."
        return

    yield f"[INFO] Leyendo Excel guardado: {excel_path.name}"
    executor = _get_executor()
    file_bytes = await executor(excel_path.read_bytes)
    raw_df = await executor(load_excel, file_bytes)
    df = await executor(_normalize, raw_df)

    # Cargar mapeos actuales de servicios
    inst_repo = InstitutionRepo(db)
    rules_repo = RulesRepo(db)

    from sqlalchemy import select as sa_select
    from app.models.institution import Service as ServiceModel
    result = await db.execute(
        sa_select(ServiceModel).where(ServiceModel.institution_id == institution.id)
    )
    service_map: dict[str, int | None] = {
        s.raw_service: s.service_type_id for s in result.scalars().all()
    }

    service_types = await rules_repo.get_service_types()
    priority_map: dict[int, int] = {st.id: st.priority for st in service_types}

    # Recalcular service_type_id por factura
    invoice_service_ids: dict[str, set[int]] = {}
    for _, row in df.iterrows():
        raw_service = str(row.get("SERVICIO", "") or "").strip()
        invoice_number = str(row["FACTURA"])
        st_id = service_map.get(raw_service)
        if st_id is not None:
            invoice_service_ids.setdefault(invoice_number, set()).add(st_id)

    updates: dict[str, int | None] = {}
    for invoice_number, st_ids in invoice_service_ids.items():
        best = max(st_ids, key=lambda sid: priority_map.get(sid, 0)) if st_ids else None
        updates[invoice_number] = best

    yield f"[INFO] Facturas a actualizar: {len(updates)}"

    inv_repo = InvoiceRepo(db)
    updated = await inv_repo.batch_update_service_type(period.id, updates)
    await db.commit()
    yield f"[OK] Tipos de servicio actualizados: {updated} factura(s)."


@_stage("RUN_STAGING")
async def _run_staging(ctx: dict) -> AsyncGenerator[str, None]:
    """Move leaf folders from DRIVE to STAGE."""
    from core.organizer import FolderCopier, LeafFolderFinder

    executor = _get_executor()
    drive_path: Path = ctx["drive_path"]
    stage_path: Path = ctx["stage_path"]

    if not drive_path.is_dir():
        yield f"[ERROR] Directorio DRIVE no existe: {drive_path}"
        return

    yield f"[INFO] Buscando carpetas hoja en {drive_path}..."
    leaf_finder = LeafFolderFinder()
    leaf_folders = await executor(leaf_finder.find_leaf_folders, drive_path)
    yield f"[INFO] Carpetas hoja encontradas: {len(leaf_folders)}"

    if leaf_folders:
        copier = FolderCopier(stage_path)
        await executor(copier.move_folders, leaf_folders, False)
        yield f"[INFO] Carpetas movidas a STAGE: {len(leaf_folders)}"
    else:
        yield "[WARN] No se encontraron carpetas hoja en DRIVE."


@_stage("CHECK_NESTED_FOLDERS")
async def _check_nested_folders(ctx: dict) -> AsyncGenerator[str, None]:
    """List invoice-level folders in STAGE that contain nested subdirectories."""
    stage_path: Path = ctx["stage_path"]

    if not stage_path.is_dir():
        yield f"[ERROR] Directorio STAGE no existe: {stage_path}"
        return

    def _find_nested(path: Path) -> list[tuple[str, list[str]]]:
        result = []
        for d in sorted(path.iterdir()):
            if d.is_dir():
                subs = [s.name for s in sorted(d.iterdir()) if s.is_dir()]
                if subs:
                    result.append((d.name, subs))
        return result

    executor = _get_executor()
    nested = await executor(_find_nested, stage_path)

    if not nested:
        yield "[INFO] No se encontraron carpetas con subcarpetas anidadas en STAGE."
        return

    yield f"[WARN] {len(nested)} carpeta(s) con subcarpetas anidadas detectadas en STAGE:"
    for name, subs in nested:
        yield f"[WARN] {name} → subcarpetas: {', '.join(subs)}"
    yield "[WARN] Revisa y aplana estas carpetas para que los archivos queden directamente en la carpeta de factura."


@_stage("REMOVE_NON_PDF")
async def _remove_non_pdf(ctx: dict) -> AsyncGenerator[str, None]:
    """Delete non-PDF files and corrupt PDFs in STAGE."""
    from core.ops import DocumentOps
    from core.reader import DocumentReader
    from core.scanner import DocumentScanner

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    scanner = DocumentScanner(stage_path)
    ops = DocumentOps(stage_path)

    # Remove non-PDF files
    non_pdf = await executor(scanner.find_non_pdf)
    yield f"[INFO] Archivos no-PDF encontrados: {len(non_pdf)}"
    if non_pdf:
        removed = await executor(ops.remove_files, non_pdf)
        yield f"[INFO] Archivos no-PDF eliminados: {removed}"

    # Remove corrupt PDFs
    all_pdfs = await executor(scanner.find_by_extension)
    yield f"[INFO] PDFs a verificar: {len(all_pdfs)}"
    invalid = await executor(DocumentReader.find_unreadable, all_pdfs)
    for f in invalid:
        yield f"[WARN] PDF corrupto: {f.name}"
    yield f"[INFO] PDFs corruptos encontrados: {len(invalid)}"
    if invalid:
        removed_corrupt = await executor(ops.remove_files, invalid)
        yield f"[INFO] PDFs corruptos eliminados: {removed_corrupt}"


def _apply_prefix_corrections(
    stage_path: Path, corrections: dict[str, str]
) -> tuple[int, list[tuple[str, str, str]]]:
    """Rename PDFs whose prefix matches a known wrong prefix to the correct one.

    Returns ``(renamed_count, [(folder_name, old_name, new_name)])``.
    """
    renamed = 0
    renames: list[tuple[str, str, str]] = []

    for pdf in stage_path.rglob("*.pdf"):
        stem = pdf.stem
        for wrong, correct in corrections.items():
            if stem.upper().startswith(wrong.upper()):
                remainder = stem[len(wrong):]
                new_name = correct + remainder + pdf.suffix
                pdf.rename(pdf.parent / new_name)
                renamed += 1
                renames.append((pdf.parent.name, pdf.name, new_name))
                break

    return renamed, renames


@_stage("NORMALIZE_FILES")
async def _normalize_files(ctx: dict) -> AsyncGenerator[str, None]:
    """Rename files with invalid names to the canonical standard.

    Step 1 — apply prefix corrections from the prefix_corrections table
              (e.g. OPD → OPF, FVE → FEV).
    Step 2 — run the generic FilenameStandardizer for remaining invalid names.
    """
    from core.scanner import DocumentScanner
    from core.standardizer import FilenameStandardizer

    from app.repositories.rules_repo import RulesRepo

    from sqlalchemy import select as _select
    from sqlalchemy.orm import selectinload as _selectinload
    from app.models.invoice import Invoice as _Invoice

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]
    period = ctx.get("period")

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)

    # -- Step 1: prefix corrections --
    corrections = await rules_repo.get_prefix_corrections_map()
    if corrections:
        renamed, renames = await executor(_apply_prefix_corrections, stage_path, corrections)
        if renamed:
            for folder, old_name, new_name in renames:
                yield f"[INFO] Renombrado: [{folder}] {old_name} → {new_name}"
            yield f"[INFO] Correcciones de prefijo aplicadas: {renamed} archivo(s)"
        else:
            yield "[INFO] Correcciones de prefijo aplicadas: 0 archivo(s)"
    else:
        yield "[INFO] Sin correcciones de prefijo configuradas"

    # -- Step 2: generic standardization --
    prefixes = await rules_repo.get_all_active_doc_type_prefixes()

    scanner = DocumentScanner(stage_path)
    invalid = await executor(
        scanner.find_invalid_names, prefixes, institution.invoice_id_prefix or "", institution.nit
    )
    yield f"[INFO] Archivos con nombre inválido: {len(invalid)}"

    if invalid:
        standardizer = FilenameStandardizer(
            nit=institution.nit,
            valid_prefixes=prefixes,
            suffix_const=institution.invoice_id_prefix or "",
        )
        results = await executor(standardizer.run, invalid)

        # Build invoice_number → contract_type_name map for the period (one query)
        _inv_admin_type: dict[str, str] = {}
        if period:
            from app.models.institution import Agreement as _IC
            _q = (
                _select(_Invoice)
                .where(_Invoice.audit_period_id == period.id)
                .options(
                    _selectinload(_Invoice.agreement).selectinload(_IC.contract_type)
                )
            )
            _rows = (await db.execute(_q)).scalars().all()
            for inv in _rows:
                if inv.agreement and inv.agreement.contract_type:
                    _inv_admin_type[inv.invoice_number] = inv.agreement.contract_type.name

        def _admin_type_for_folder(folder: str) -> str:
            """Exact match first, then substring (folder may have extra prefix)."""
            if folder in _inv_admin_type:
                return _inv_admin_type[folder]
            for num, atype in _inv_admin_type.items():
                if num in folder:
                    return atype
            return ""

        success = 0
        for r in results:
            original_path = Path(r.original_path)
            folder = original_path.parent.name
            old_name = original_path.name
            admin_type = _admin_type_for_folder(folder)
            admin_suffix = f" [{admin_type}]" if admin_type else ""
            if r.status == "SUCCESS":
                success += 1
                yield f"[INFO] Renombrado: [{folder}] {old_name} → {r.new_name}"
            elif r.status == "REJECTED":
                if "Could not find" in r.reason:
                    yield f"[WARN] Sin ID de factura extraíble: [{folder}]{admin_suffix} {old_name}"
                elif "already exists" in r.reason:
                    yield f"[WARN] Destino ya existe: [{folder}]{admin_suffix} {old_name} → {r.new_name}"
                else:
                    # Covers empty prefix (starts with digit) and unrecognised prefixes
                    yield f"[WARN] Prefijo no reconocido: [{folder}]{admin_suffix} {old_name}"
            elif r.status == "ERROR":
                yield f"[ERROR] No se pudo renombrar: [{folder}]{admin_suffix} {old_name} — {r.reason}"
        yield f"[INFO] Archivos renombrados: {success}/{len(invalid)}"


@_stage("LIST_UNREADABLE_PDFS")
async def _list_unreadable_pdfs(ctx: dict) -> AsyncGenerator[str, None]:
    """List invoice PDFs without a text layer (need OCR)."""
    from core.reader import DocumentReader
    from core.scanner import DocumentScanner

    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else (institution.invoice_id_prefix or "")

    scanner = DocumentScanner(stage_path)
    invoices = await executor(scanner.find_by_prefix, invoice_prefix)
    yield f"[INFO] PDFs de factura encontrados: {len(invoices)}"

    no_text = await executor(DocumentReader.find_needing_ocr, invoices)
    for f in no_text:
        yield f"[WARN] Sin capa de texto: {f.name}"
    yield f"[INFO] Facturas sin texto: {len(no_text)}"


@_stage("DELETE_UNREADABLE_PDFS")
async def _delete_unreadable_pdfs(ctx: dict) -> AsyncGenerator[str, None]:
    """Delete invoice PDFs without a text layer."""
    from core.reader import DocumentReader
    from core.scanner import DocumentScanner

    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else (institution.invoice_id_prefix or "")

    scanner = DocumentScanner(stage_path)
    invoices = await executor(scanner.find_by_prefix, invoice_prefix)
    no_text = await executor(DocumentReader.find_needing_ocr, invoices)
    yield f"[INFO] PDFs sin texto a eliminar: {len(no_text)}"

    deleted = 0
    for f in no_text:
        try:
            f.unlink()
            deleted += 1
            yield f"[INFO] Eliminado: {f.name}"
        except OSError as exc:
            yield f"[ERROR] No se pudo eliminar {f.name}: {exc}"
    yield f"[INFO] Total eliminados: {deleted}"


@_stage("DOWNLOAD_INVOICES_FROM_SIHOS")
async def _download_invoices_from_sihos(ctx: dict) -> AsyncGenerator[str, None]:
    """Download the factura PDF from SIHOS for PENDIENTE invoices with an unresolved finding of the chosen doc type."""
    from sqlalchemy import select

    from core.downloader import SihosDownloader

    from app.crypto import decrypt
    from app.models.finding import MissingFile
    from app.models.invoice import Invoice
    from app.models.rules import DocType, FolderStatus

    institution = ctx["institution"]
    stage_path: Path = ctx["stage_path"]
    db = ctx["db"]
    period = ctx["period"]
    doc_type_id: int = ctx.get("doc_type_id", 0)

    if not doc_type_id:
        yield "[ERROR] No se seleccionó un tipo de documento. Elige uno en el panel antes de ejecutar esta etapa."
        return

    if not institution.sihos_user or not institution.sihos_password:
        yield "[ERROR] Credenciales SIHOS no configuradas en la institución."
        return

    doc_type_result = await db.execute(select(DocType).where(DocType.id == doc_type_id))
    doc_type = doc_type_result.scalar_one_or_none()
    if not doc_type:
        yield f"[ERROR] Tipo de documento con id={doc_type_id} no encontrado."
        return

    yield f"[INFO] Tipo de documento: {doc_type.code} — prefijo {doc_type.prefix or '(sin prefijo)'}"

    stmt = (
        select(Invoice.invoice_number)
        .join(FolderStatus, Invoice.folder_status_id == FolderStatus.id)
        .join(MissingFile, MissingFile.invoice_id == Invoice.id)
        .where(Invoice.audit_period_id == period.id)
        .where(FolderStatus.status == "PENDIENTE")
        .where(MissingFile.doc_type_id == doc_type_id)
        .where(MissingFile.resolved_at.is_(None))
        .distinct()
    )
    result = await db.execute(stmt)
    invoice_numbers = [row.invoice_number for row in result.all()]

    if not invoice_numbers:
        yield f"[INFO] No hay facturas PENDIENTE con hallazgo {doc_type.code} sin resolver."
        return

    yield f"[INFO] Descargando {len(invoice_numbers)} factura(s) desde SIHOS..."

    executor = _get_executor()
    password = decrypt(institution.sihos_password)
    downloader = SihosDownloader(
        user=institution.sihos_user,
        password=password,
        base_url=institution.sihos_base_url or "",
        hospital_nit=institution.nit,
        invoice_prefix=doc_type.prefix or "",
        invoice_id_prefix=institution.invoice_id_prefix or "",
        invoice_doc_code=institution.sihos_doc_code or "",
        output_dir=stage_path,
    )

    await executor(downloader.run_from_list, invoice_numbers)
    yield "[INFO] Descarga SIHOS completada."


@_stage("DOWNLOAD_MEDICATION_SHEETS")
async def _download_medication_sheets(ctx: dict) -> AsyncGenerator[str, None]:
    """Download PDFs for PENDIENTE invoices with an unresolved finding of the chosen doc type."""
    from sqlalchemy import select

    from core.downloader import SihosDownloader

    from app.crypto import decrypt
    from app.models.finding import MissingFile
    from app.models.invoice import Invoice
    from app.models.rules import DocType, FolderStatus

    institution = ctx["institution"]
    stage_path: Path = ctx["stage_path"]
    db = ctx["db"]
    period = ctx["period"]
    doc_type_id: int = ctx.get("doc_type_id", 0)

    if not doc_type_id:
        yield "[ERROR] No se seleccionó un tipo de documento. Elige uno en el panel antes de ejecutar esta etapa."
        return

    if not institution.sihos_user or not institution.sihos_password:
        yield "[ERROR] Credenciales SIHOS no configuradas en la institución."
        return

    doc_type_result = await db.execute(select(DocType).where(DocType.id == doc_type_id))
    doc_type = doc_type_result.scalar_one_or_none()
    if not doc_type:
        yield f"[ERROR] Tipo de documento con id={doc_type_id} no encontrado."
        return

    yield f"[INFO] Tipo de documento seleccionado: {doc_type.code} — {doc_type.description}"

    stmt = (
        select(Invoice.invoice_number, Invoice.admission, Invoice.id_number)
        .join(FolderStatus, Invoice.folder_status_id == FolderStatus.id)
        .join(MissingFile, MissingFile.invoice_id == Invoice.id)
        .where(Invoice.audit_period_id == period.id)
        .where(Invoice.admission.isnot(None))
        .where(FolderStatus.status == "PENDIENTE")
        .where(MissingFile.doc_type_id == doc_type_id)
        .where(MissingFile.resolved_at.is_(None))
        .distinct()
    )
    result = await db.execute(stmt)
    targets: list[tuple[str, str, str]] = [
        (row.invoice_number, row.admission, row.id_number)
        for row in result.all()
    ]

    if not targets:
        yield f"[INFO] No hay facturas PENDIENTE con hallazgo {doc_type.code} sin resolver y número de admisión."
        return

    yield f"[INFO] Descargando {len(targets)} factura(s) desde SIHOS..."

    executor = _get_executor()
    password = decrypt(institution.sihos_password)
    downloader = SihosDownloader(
        user=institution.sihos_user,
        password=password,
        base_url=institution.sihos_base_url or "",
        hospital_nit=institution.nit,
        invoice_prefix="",
        invoice_id_prefix=institution.invoice_id_prefix or "",
        invoice_doc_code=institution.sihos_doc_code or "",
        output_dir=stage_path,
    )

    file_prefix = doc_type.prefix or doc_type.code
    await executor(downloader.run_medication_sheets, targets, file_prefix)
    yield "[INFO] Descarga completada."


@_stage("CHECK_INVOICES")
async def _check_invoices(ctx: dict) -> AsyncGenerator[str, None]:
    """Apply OCR to invoice PDFs without a text layer."""
    from core.processor import DocumentProcessor
    from core.reader import DocumentReader
    from core.scanner import DocumentScanner

    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else (institution.invoice_id_prefix or "")

    scanner = DocumentScanner(stage_path)
    invoices = await executor(scanner.find_by_prefix, invoice_prefix)
    needing_ocr = await executor(DocumentReader.find_needing_ocr, invoices)
    yield f"[INFO] Facturas que requieren OCR: {len(needing_ocr)}"

    if needing_ocr:
        result = await executor(DocumentProcessor.batch_ocr, needing_ocr, 8)
        yield f"[INFO] OCR completado — exitosos: {result['success']}, fallidos: {result['failed']}"
    else:
        yield "[INFO] Ninguna factura requiere OCR."


@_stage("VERIFY_INVOICE_CODE")
async def _verify_invoice_code(ctx: dict) -> AsyncGenerator[str, None]:
    """Verify that each invoice PDF contains its own invoice number in the text."""
    from core.scanner import DocumentScanner
    from core.validator import InvoiceValidator

    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else (institution.invoice_id_prefix or "")

    scanner = DocumentScanner(stage_path)
    invoices = await executor(scanner.find_by_prefix, invoice_prefix)

    validator = InvoiceValidator(stage_path, institution.invoice_id_prefix or "")
    missing_code, _ = await executor(validator.validate_invoice_files, invoices)
    for f in missing_code:
        yield f"[WARN] Sin número de factura en PDF: {f.name}"
    yield f"[INFO] Facturas sin código: {len(missing_code)}"


@_stage("CHECK_INVOICE_NUMBER_ON_FILES")
async def _check_invoice_number_on_files(ctx: dict) -> AsyncGenerator[str, None]:
    """Verify that files inside each invoice folder match the folder name."""
    from core.inspector import FolderInspector

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inspector = FolderInspector(stage_path, institution.invoice_id_prefix or "")
    mismatched = await executor(inspector.find_mismatched_files)
    for f in mismatched:
        yield f"[WARN] Archivo desajustado: {f.name} (en carpeta {f.parent.name})"
    yield f"[INFO] Archivos desajustados: {len(mismatched)}"


@_stage("CHECK_FOLDERS_WITH_EXTRA_TEXT")
async def _check_folders_with_extra_text(ctx: dict) -> AsyncGenerator[str, None]:
    """Detect folders with extra text in their names."""
    from core.inspector import FolderInspector

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inspector = FolderInspector(stage_path, institution.invoice_id_prefix or "")
    malformed = await executor(inspector.find_malformed_dirs)
    for d in malformed:
        yield f"[WARN] Carpeta con texto extra: {d.name}"
    yield f"[INFO] Carpetas malformadas: {len(malformed)}"


@_stage("NORMALIZE_DIR_NAMES")
async def _normalize_dir_names(ctx: dict) -> AsyncGenerator[str, None]:
    """Rename folders with extra text to their canonical identifier."""
    from core.inspector import FolderInspector
    from core.ops import DocumentOps

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inspector = FolderInspector(stage_path, institution.invoice_id_prefix or "")
    malformed = await executor(inspector.find_malformed_dirs)
    yield f"[INFO] Carpetas malformadas encontradas: {len(malformed)}"

    if malformed:
        ops = DocumentOps(stage_path, institution.invoice_id_prefix or "")
        renamed = await executor(ops.standardize_dir_names, malformed)
        yield f"[INFO] Carpetas renombradas: {renamed}"


@_stage("CHECK_DIRS")
async def _check_dirs(ctx: dict) -> AsyncGenerator[str, None]:
    """Compare invoice numbers in DB against folders on disk; mark missing ones FALTANTE."""
    from core.inspector import FolderInspector

    from app.repositories.invoice_repo import InvoiceRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inv_repo = InvoiceRepo(db)
    presente_numbers = await inv_repo.get_invoice_numbers_by_status(period.id, "PRESENTE")
    yield f"[INFO] Facturas PRESENTE en BD: {len(presente_numbers)}"

    inspector = FolderInspector(stage_path, institution.invoice_id_prefix or "")
    missing = await executor(inspector.find_missing_dirs, presente_numbers)
    yield f"[INFO] Facturas sin carpeta en disco: {len(missing)}"

    if missing:
        updated = await inv_repo.batch_update_folder_status(period.id, missing, "FALTANTE")
        await db.commit()
        yield f"[INFO] Marcadas como FALTANTE: {updated}"
        for name in missing:
            yield f"[WARN] Sin carpeta: {name}"


@_stage("CHECK_REQUIRED_DOCS")
async def _check_required_docs(ctx: dict) -> AsyncGenerator[str, None]:
    """Verify required documents per service type; record findings for missing ones."""
    from core.inspector import FolderInspector

    from app.repositories.finding_repo import MissingFileRepo
    from app.repositories.invoice_repo import InvoiceRepo
    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inv_repo = InvoiceRepo(db)
    rules_repo = RulesRepo(db)
    finding_repo = MissingFileRepo(db)

    std_map = await rules_repo.get_service_type_docs_map(institution.id)
    prefix_map = await rules_repo.get_active_doc_types_map()

    presente_invoices = await inv_repo.get_invoices_by_status_code(period.id, "PRESENTE")
    yield f"[INFO] Facturas PRESENTE a verificar: {len(presente_invoices)}"

    id_prefix = institution.invoice_id_prefix or ""
    inspector = FolderInspector(stage_path, id_prefix)

    # Snapshot data needed in executor (avoids passing SQLAlchemy objects to thread)
    invoice_data = [
        (inv.id, inv.invoice_number, inv.service_type_id)
        for inv in presente_invoices
    ]

    def _check_all_folders(
        inv_data: list[tuple[int, str, int | None]],
    ) -> dict[int, tuple[str, list[int]]]:
        """Returns {invoice_id: (invoice_number, [missing_doc_type_ids])}"""
        results: dict[int, tuple[str, list[int]]] = {}
        for inv_id, inv_number, svc_type_id in inv_data:
            required_dt_ids = std_map.get(svc_type_id, [])
            if not required_dt_ids:
                continue
            required_prefixes = {
                str(dt_id): prefix_map.get(dt_id, [])
                for dt_id in required_dt_ids
            }
            folder = stage_path / (id_prefix + inv_number)
            missing_codes = inspector.check_required_docs(folder, required_prefixes)
            if missing_codes:
                results[inv_id] = (inv_number, [int(c) for c in missing_codes])
        return results

    findings_map = await executor(_check_all_folders, invoice_data)

    # Bulk upsert all findings in one DB call
    all_findings: list[tuple[int, int]] = [
        (inv_id, dt_id)
        for inv_id, (_, dt_ids) in findings_map.items()
        for dt_id in dt_ids
    ]
    total_findings = len(all_findings)
    await finding_repo.bulk_upsert_findings(all_findings)

    invoices_with_findings = [inv_number for _, (inv_number, _) in findings_map.items()]
    for inv_number, (_, dt_ids) in findings_map.items():
        yield f"[WARN] Faltantes en {dt_ids[0] if len(dt_ids)==1 else str(len(dt_ids))+' docs'}: {inv_number}"

    if invoices_with_findings:
        updated = await inv_repo.batch_update_folder_status(
            period.id, invoices_with_findings, "PENDIENTE"
        )
        yield f"[INFO] Facturas marcadas PENDIENTE: {updated}"

    await db.commit()
    yield f"[INFO] Hallazgos totales registrados: {total_findings}"


def _compute_surplus_suggestions(sobrantes, faltantes, SequenceMatcher):
    """Returns {filename: {suggested_doc_type_id, suggested_code, suggested_prefix, confidence}}"""
    if not faltantes:
        return {}

    result = {}

    if len(sobrantes) == 1 and len(faltantes) == 1:
        dt = faltantes[0].doc_type
        result[sobrantes[0].name] = {
            "suggested_doc_type_id": dt.id,
            "suggested_code": dt.code,
            "suggested_prefix": dt.prefix,
            "confidence": "high",
        }
    else:
        for f in sobrantes:
            best_score = 0.0
            best_dt = None
            for mf in faltantes:
                dt = mf.doc_type
                if not dt or not dt.prefix:
                    continue
                score = SequenceMatcher(None, f.name.upper(), dt.prefix.upper()).ratio()
                if score > best_score:
                    best_score = score
                    best_dt = dt
            if best_dt and best_score > 0.3:
                result[f.name] = {
                    "suggested_doc_type_id": best_dt.id,
                    "suggested_code": best_dt.code,
                    "suggested_prefix": best_dt.prefix,
                    "confidence": "low",
                }
    return result


@_stage("REVISAR_SOBRANTES")
async def _revisar_sobrantes(ctx: dict) -> AsyncGenerator[str, None]:
    """Identify surplus files per invoice folder and suggest doc-type renames."""
    import json
    from difflib import SequenceMatcher

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.finding import MissingFile
    from app.models.institution import Agreement
    from app.models.invoice import Invoice
    from app.repositories.invoice_repo import InvoiceRepo
    from app.repositories.rules_repo import RulesRepo

    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db: AsyncSession = ctx["db"]

    if not stage_path.exists():
        yield "[ERROR] Directorio STAGE no existe"
        return

    rules_repo = RulesRepo(db)
    std_map = await rules_repo.get_service_type_docs_map(institution.id)
    raw_prefix_map = await rules_repo.get_active_doc_types_map()
    prefix_map = {k: v[0] if v else None for k, v in raw_prefix_map.items()}

    q = (
        select(Invoice)
        .where(Invoice.audit_period_id == period.id)
        .options(
            selectinload(Invoice.agreement).selectinload(Agreement.contract_type),
            selectinload(Invoice.service_type),
            selectinload(Invoice.missing_files).selectinload(MissingFile.doc_type),
        )
    )
    result = await db.execute(q)
    invoices = list(result.scalars().all())
    invoice_by_number = {inv.invoice_number.upper(): inv for inv in invoices}

    # Snapshot invoice data to pass to executor (avoid passing SQLAlchemy ORM objects)
    invoice_snapshot = {
        num: {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "service_type_id": inv.service_type_id,
            "admin_type": inv.agreement.contract_type.name if inv.agreement and inv.agreement.contract_type else None,
            "service_type": inv.service_type.display_name if inv.service_type else None,
            "faltantes": [
                {
                    "doc_type_id": mf.doc_type.id,
                    "code": mf.doc_type.code,
                    "description": mf.doc_type.description,
                    "prefix": mf.doc_type.prefix if hasattr(mf.doc_type, "prefix") else None,
                    "_prefix_for_suggestion": mf.doc_type.prefix if hasattr(mf.doc_type, "prefix") else None,
                }
                for mf in inv.missing_files
                if mf.resolved_at is None and mf.doc_type
            ],
        }
        for num, inv in invoice_by_number.items()
    }

    executor = _get_executor()

    def _scan_folders(
        s_path: Path,
        inv_snap: dict,
        s_std_map: dict,
        s_prefix_map: dict,
    ) -> tuple[list[dict], list[str], int]:
        from difflib import SequenceMatcher as SM
        items_out: list[dict] = []
        log_lines: list[str] = []
        total = 0

        for folder in sorted(s_path.iterdir()):
            if not folder.is_dir():
                continue

            folder_key = folder.name.upper()
            inv_data = inv_snap.get(folder_key)
            if inv_data is None:
                inv_data = next(
                    (v for k, v in inv_snap.items()
                     if folder_key == k
                     or folder_key.startswith(k + "_")
                     or folder_key.startswith(k + " ")
                     or folder_key.endswith(k)),
                    None,
                )
            if inv_data is None:
                continue

            required_dt_ids = s_std_map.get(inv_data["service_type_id"], [])
            required_prefixes = [
                s_prefix_map[dt_id]
                for dt_id in required_dt_ids
                if dt_id in s_prefix_map and s_prefix_map[dt_id]
            ]

            all_files = [f for f in folder.iterdir() if f.is_file()]
            sobrantes = [
                f for f in all_files
                if not any(f.name.upper().startswith(p.upper()) for p in required_prefixes)
            ]
            if not sobrantes:
                continue

            faltantes_data = inv_data["faltantes"]

            # Compute suggestions inline (reimplemented to avoid passing SequenceMatcher objects)
            suggestions: dict = {}
            if faltantes_data:
                if len(sobrantes) == 1 and len(faltantes_data) == 1:
                    ft = faltantes_data[0]
                    suggestions[sobrantes[0].name] = {
                        "suggested_doc_type_id": ft["doc_type_id"],
                        "suggested_code": ft["code"],
                        "suggested_prefix": ft.get("_prefix_for_suggestion"),
                        "confidence": "high",
                    }
                else:
                    for f in sobrantes:
                        best_score, best_ft = 0.0, None
                        for ft in faltantes_data:
                            prefix = ft.get("_prefix_for_suggestion") or ""
                            if not prefix:
                                continue
                            score = SM(None, f.name.upper(), prefix.upper()).ratio()
                            if score > best_score:
                                best_score, best_ft = score, ft
                        if best_ft and best_score > 0.3:
                            suggestions[f.name] = {
                                "suggested_doc_type_id": best_ft["doc_type_id"],
                                "suggested_code": best_ft["code"],
                                "suggested_prefix": best_ft.get("_prefix_for_suggestion"),
                                "confidence": "low",
                            }

            items_out.append({
                "invoice_id": inv_data["id"],
                "invoice_number": inv_data["invoice_number"],
                "admin_type": inv_data["admin_type"],
                "service_type": inv_data["service_type"],
                "folder_path": str(folder),
                "sobrantes": [
                    {
                        "filename": f.name,
                        **suggestions.get(f.name, {
                            "suggested_doc_type_id": None,
                            "suggested_code": None,
                            "suggested_prefix": None,
                            "confidence": None,
                        }),
                    }
                    for f in sobrantes
                ],
                "faltantes": [
                    {"doc_type_id": ft["doc_type_id"], "code": ft["code"], "description": ft["description"]}
                    for ft in faltantes_data
                ],
            })
            total += len(sobrantes)
            log_lines.append(f"[INFO] {folder.name}: {len(sobrantes)} sobrante(s), {len(faltantes_data)} faltante(s)")

        return items_out, log_lines, total

    items, log_lines, total_sobrantes = await executor(
        _scan_folders, stage_path, invoice_snapshot, std_map, prefix_map
    )

    for line in log_lines:
        yield line

    yield f"[INFO] Total: {total_sobrantes} archivos sobrantes en {len(items)} carpetas"
    if items:
        yield f"[DATA] {json.dumps(items, ensure_ascii=False)}"
    else:
        yield "[INFO] No se encontraron archivos sobrantes"


@_stage("VERIFY_CUFE")
async def _verify_cufe(ctx: dict) -> AsyncGenerator[str, None]:
    """Verify CUFE presence and tag folders missing a CUFE in invoice PDFs."""
    from core.ops import DocumentOps
    from core.scanner import DocumentScanner
    from core.validator import InvoiceValidator

    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else (institution.invoice_id_prefix or "")

    scanner = DocumentScanner(stage_path)
    invoices = await executor(scanner.find_by_prefix, invoice_prefix)

    validator = InvoiceValidator(stage_path, institution.invoice_id_prefix or "")
    _, missing_cufe = await executor(validator.validate_invoice_files, invoices)
    for f in missing_cufe:
        yield f"[WARN] Sin CUFE: {f.name}"
    yield f"[INFO] Facturas sin CUFE: {len(missing_cufe)}"

    if missing_cufe:
        ops = DocumentOps(stage_path, institution.invoice_id_prefix or "")
        marked = await executor(ops.tag_dirs_missing_cufe, missing_cufe)
        yield f"[INFO] Carpetas marcadas sin CUFE: {marked}"


@_stage("ORGANIZE")
async def _organize(ctx: dict) -> AsyncGenerator[str, None]:
    """Move eligible invoices (PRESENTE + no findings) to AUDIT/ADMIN[/CONTRACT]/FOLDER."""
    from core.helpers import safe_move

    from app.repositories.invoice_repo import InvoiceRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    audit_path: Path = ctx["audit_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db = ctx["db"]

    if not stage_path.is_dir():
        yield f"[WARN] Directorio STAGE no existe: {stage_path}"
        return

    inv_repo = InvoiceRepo(db)
    organizable = await inv_repo.get_organizable_invoices(period.id)
    yield f"[INFO] Facturas organizables: {len(organizable)}"

    if not organizable:
        yield "[INFO] Nada que organizar."
        return

    # Index staging folders once (case-insensitive) for fast lookup
    def _build_staging_index(stage: Path) -> dict[str, Path]:
        return {p.name.upper(): p for p in stage.iterdir() if p.is_dir()}

    staging_index = await executor(_build_staging_index, stage_path)
    id_prefix = (institution.invoice_id_prefix or "").upper()

    # Build all (source, dest, invoice_number) triples first — no I/O yet
    planned: list[tuple[Path, Path, str]] = []
    not_found = 0

    for inv in organizable:
        folder_name = (institution.invoice_id_prefix or "") + inv.invoice_number
        source = staging_index.get(folder_name.upper())
        if source is None:
            key = folder_name.upper()
            source = next(
                (
                    p for name, p in staging_index.items()
                    if (name.startswith(key) and (len(name) == len(key) or not name[len(key)].isalnum()))
                    or (id_prefix and name.endswith(inv.invoice_number.upper()))
                ),
                None,
            )
        if source is None:
            yield f"[WARN] Carpeta no encontrada en STAGE: {folder_name}"
            not_found += 1
            continue

        ic = inv.agreement
        if ic and ic.administrator and ic.administrator.canonical_name:
            admin_name = (
                f"{ic.administrator.canonical_name} ({ic.contract_type.name})"
                if ic.contract_type
                else ic.administrator.canonical_name
            )
        else:
            admin_name = "SIN ADMINISTRADORA"
        contract_name = (
            ic.contract.canonical_name
            if ic and ic.contract and ic.contract.canonical_name
            else None
        )
        dest = (
            audit_path / admin_name / contract_name / source.name
            if contract_name
            else audit_path / admin_name / source.name
        )
        planned.append((source, dest, inv.invoice_number))

    def _batch_move(
        moves: list[tuple[Path, Path, str]],
    ) -> tuple[list[tuple[str, str]], list[str]]:
        """Returns ([(src_name, rel_dest), ...], [failed_src_names])."""
        moved, failed = [], []
        for src, dest, _ in moves:
            if safe_move(src, dest):
                moved.append((src.name, str(dest.relative_to(audit_path))))
            else:
                failed.append(src.name)
        return moved, failed

    moved_pairs, failed_names = await executor(_batch_move, planned)
    moved_numbers = [inv_number for _, _, inv_number in planned if
                     any(src == name for name, _ in moved_pairs
                         for src, _, _ in [p for p in planned if p[2] == inv_number])]

    # Simpler: derive moved_numbers from planned vs failed
    failed_set = set(failed_names)
    moved_numbers = [inv_number for src, _, inv_number in planned if src.name not in failed_set]

    for src_name, rel_dest in moved_pairs:
        yield f"[INFO] Movida: {src_name} → {rel_dest}"
    for src_name in failed_names:
        yield f"[WARN] Error al mover: {src_name}"

    yield f"[INFO] Movidas: {len(moved_numbers)}, no encontradas: {not_found}, fallidas: {len(failed_names)}"

    if moved_numbers:
        updated = await inv_repo.batch_update_to_auditada(period.id, moved_numbers)
        await db.commit()
        yield f"[INFO] Facturas marcadas AUDITADA: {updated}"


@_stage("DOWNLOAD_DRIVE")
async def _download_drive(ctx: dict) -> AsyncGenerator[str, None]:
    """Download FALTANTE invoice folders from Google Drive."""
    from core.drive import DriveSync

    from app.crypto import decrypt
    from app.repositories.invoice_repo import InvoiceRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db = ctx["db"]

    if not institution.drive_credentials_enc:
        yield "[ERROR] Credenciales de Drive no configuradas en la institución."
        return

    inv_repo = InvoiceRepo(db)
    missing = await inv_repo.get_invoice_numbers_by_status(period.id, "FALTANTE")
    yield f"[INFO] Facturas FALTANTE a buscar en Drive: {len(missing)}"

    if not missing:
        yield "[INFO] No hay facturas FALTANTE."
        return

    creds = json.loads(decrypt(institution.drive_credentials_enc))
    drive = DriveSync(credentials_dict=creds)

    id_prefix = institution.invoice_id_prefix or ""
    # Folders on disk (and in Drive) are named PREFIX+invoice_number
    search_names = [id_prefix + num for num in missing]
    for sn in search_names:
        yield f"[INFO] Buscando en Drive: {sn}"

    stage_path.mkdir(parents=True, exist_ok=True)
    downloaded_prefixed = await executor(drive.download_missing_dirs, search_names, stage_path)
    yield f"[INFO] Carpetas descargadas de Drive: {len(downloaded_prefixed)}/{len(missing)}"

    if downloaded_prefixed:
        # Strip prefix back to plain invoice numbers for DB update
        downloaded = [
            name[len(id_prefix):] if (id_prefix and name.upper().startswith(id_prefix.upper())) else name
            for name in downloaded_prefixed
        ]
        updated = await inv_repo.batch_update_folder_status(period.id, downloaded, "PRESENTE")
        await db.commit()
        yield f"[INFO] Facturas actualizadas a PRESENTE: {updated}"


@_stage("DOWNLOAD_MISSING_DOCS")
async def _download_missing_docs(ctx: dict) -> AsyncGenerator[str, None]:
    """Download specific missing document files from Google Drive."""
    from core.drive import DriveSync

    from app.crypto import decrypt
    from app.repositories.finding_repo import MissingFileRepo
    from app.repositories.rules_repo import RulesRepo

    executor = _get_executor()
    stage_path: Path = ctx["stage_path"]
    institution = ctx["institution"]
    period = ctx["period"]
    db = ctx["db"]

    if not institution.drive_credentials_enc:
        yield "[ERROR] Credenciales de Drive no configuradas en la institución."
        return

    finding_repo = MissingFileRepo(db)
    rules_repo = RulesRepo(db)

    grouped = await finding_repo.get_findings_grouped_by_invoice(period.id)
    yield f"[INFO] Facturas con documentos faltantes: {len(grouped)}"

    if not grouped:
        yield "[INFO] No hay documentos faltantes."
        return

    doc_types = await rules_repo.get_doc_types()
    prefix_by_code = {dt.code: dt.prefix for dt in doc_types if dt.prefix}

    creds = json.loads(decrypt(institution.drive_credentials_enc))
    drive = DriveSync(credentials_dict=creds)

    id_prefix = institution.invoice_id_prefix or ""
    total_files = 0
    for invoice_number, doc_codes in grouped.items():
        file_names = [
            f"{prefix_by_code[code]}_{institution.nit}_{invoice_number}.pdf"
            for code in doc_codes
            if code in prefix_by_code
        ]
        if file_names:
            dest_folder = stage_path / (id_prefix + invoice_number)
            dest_folder.mkdir(parents=True, exist_ok=True)
            await executor(drive.download_specific_files, file_names, dest_folder)
            total_files += len(file_names)
            yield f"[INFO] {invoice_number}: buscando {len(file_names)} documento(s) en Drive"

    yield f"[INFO] Total archivos buscados en Drive: {total_files}"
