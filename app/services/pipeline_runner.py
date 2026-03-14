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

    yield f"[INFO] Iniciando etapa: {stage}"
    try:
        async for line in handler_fn(ctx):
            yield line
        yield f"[INFO] Etapa completada: {stage}"
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

        # Build invoice_number → admin_type map for the period (one query)
        _inv_admin_type: dict[str, str] = {}
        if period:
            _q = (
                _select(_Invoice)
                .where(_Invoice.audit_period_id == period.id)
                .options(_selectinload(_Invoice.admin))
            )
            _rows = (await db.execute(_q)).scalars().all()
            for inv in _rows:
                if inv.admin and inv.admin.type:
                    _inv_admin_type[inv.invoice_number] = inv.admin.type

        def _admin_type_for_folder(folder: str) -> str:
            """Exact match first, then substring (folder may have extra prefix)."""
            if folder in _inv_admin_type:
                return _inv_admin_type[folder]
            for num, atype in _inv_admin_type.items():
                if num in folder:
                    return atype
            return ""

        import re as _re
        _re_pref = _re.compile(r"Prefix '(\w+)'")
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
                if _re_pref.search(r.reason):
                    yield f"[WARN] Prefijo no reconocido: [{folder}]{admin_suffix} {old_name}"
                elif "Could not find" in r.reason:
                    yield f"[WARN] Sin ID de factura extraíble: [{folder}]{admin_suffix} {old_name}"
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
    """Download invoices from SIHOS portal via Playwright.

    Requires ctx['invoice_numbers'] — a list of invoice number strings provided
    by the user through the UI textarea before running this stage.
    """
    from core.downloader import SihosDownloader

    from app.crypto import decrypt
    from app.repositories.rules_repo import RulesRepo

    institution = ctx["institution"]
    stage_path: Path = ctx["stage_path"]
    db = ctx["db"]
    invoice_numbers: list[str] = ctx.get("invoice_numbers", [])

    if not invoice_numbers:
        yield "[WARN] No se especificaron facturas para descargar. Ingresa los números en el campo de texto antes de ejecutar esta etapa."
        return

    if not institution.sihos_user or not institution.sihos_password:
        yield "[ERROR] Credenciales SIHOS no configuradas en la institución."
        return

    rules_repo = RulesRepo(db)
    invoice_doc = await rules_repo.get_doc_type_by_code("FACTURA")
    invoice_prefix = invoice_doc.prefix if invoice_doc and invoice_doc.prefix else ""

    executor = _get_executor()
    password = decrypt(institution.sihos_password)
    downloader = SihosDownloader(
        user=institution.sihos_user,
        password=password,
        base_url=institution.sihos_base_url or "",
        hospital_nit=institution.nit,
        invoice_prefix=invoice_prefix,
        invoice_id_prefix=institution.invoice_id_prefix or "",
        invoice_doc_code=institution.sihos_doc_code or "",
        output_dir=stage_path,
    )

    yield f"[INFO] Descargando {len(invoice_numbers)} factura(s) desde SIHOS..."
    await executor(downloader.run_from_list, invoice_numbers)
    yield f"[INFO] Descarga SIHOS completada."


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

    inspector = FolderInspector(stage_path, institution.invoice_id_prefix or "")
    total_findings = 0
    invoices_with_findings: list[str] = []

    for invoice in presente_invoices:
        required_dt_ids = std_map.get(invoice.service_type_id, [])
        if not required_dt_ids:
            continue

        required_prefixes = {
            str(dt_id): prefix_map.get(dt_id, [])
            for dt_id in required_dt_ids
        }

        prefix = institution.invoice_id_prefix or ""
        folder = stage_path / (prefix + invoice.invoice_number)
        missing_codes = await executor(inspector.check_required_docs, folder, required_prefixes)

        for code in missing_codes:
            await finding_repo.upsert_finding(invoice.id, int(code))
            total_findings += 1

        if missing_codes:
            invoices_with_findings.append(invoice.invoice_number)
            yield f"[WARN] Faltantes en {invoice.invoice_number}: doc_type_ids {missing_codes}"

    if invoices_with_findings:
        updated = await inv_repo.batch_update_folder_status(
            period.id, invoices_with_findings, "PENDIENTE"
        )
        yield f"[INFO] Facturas marcadas PENDIENTE: {updated}"

    await db.commit()
    yield f"[INFO] Hallazgos totales registrados: {total_findings}"


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

    moved_numbers: list[str] = []
    not_found = 0
    failed = 0

    for inv in organizable:
        # Folder on disk: PREFIX + invoice_number (e.g. HSL359918)
        folder_name = (institution.invoice_id_prefix or "") + inv.invoice_number

        # Find source — exact match first, then prefix-stripped fallback
        source = staging_index.get(folder_name.upper())
        if source is None:
            # Fallback: folder name ends with the invoice number (handles edge cases)
            source = next(
                (p for name, p in staging_index.items() if name.endswith(inv.invoice_number.upper())),
                None,
            )

        if source is None:
            yield f"[WARN] Carpeta no encontrada en STAGE: {folder_name}"
            not_found += 1
            continue

        # Build destination: AUDIT / ADMIN / [CONTRACT /] folder_name
        admin_name = (
            inv.admin.canonical_admin
            if inv.admin and inv.admin.canonical_admin
            else "SIN ADMINISTRADORA"
        )
        contract_name = (
            inv.contract.canonical_contract
            if inv.contract and inv.contract.canonical_contract
            else None
        )

        if contract_name:
            dest = audit_path / admin_name / contract_name / source.name
        else:
            dest = audit_path / admin_name / source.name

        ok = await executor(safe_move, source, dest)
        if ok:
            moved_numbers.append(inv.invoice_number)
            yield f"[INFO] Movida: {source.name} → {dest.relative_to(audit_path)}"
        else:
            failed += 1
            yield f"[WARN] Error al mover: {source.name}"

    yield f"[INFO] Movidas: {len(moved_numbers)}, no encontradas: {not_found}, fallidas: {failed}"

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
