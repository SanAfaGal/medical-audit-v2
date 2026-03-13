"""Tests for app/services/pipeline_runner.py — dispatch + stage error handling."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS, execute


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_all_keys_present(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {})
        for key in ("institution", "period", "db", "base_path", "drive_path", "stage_path", "audit_path"):
            assert key in ctx

    def test_paths_derived_from_base(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {})
        base = Path(minimal_institution.base_path) / minimal_period.period_label
        assert ctx["base_path"] == base
        assert ctx["drive_path"] == base / "DRIVE"
        assert ctx["stage_path"] == base / "STAGE"
        assert ctx["audit_path"] == base / "AUDIT"

    def test_extra_keys_merged(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {"invoice_numbers": ["X"]})
        assert ctx["invoice_numbers"] == ["X"]


# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------

class TestStageRegistry:
    def test_all_21_stages_registered(self):
        expected = {
            "LOAD_AND_PROCESS", "RUN_STAGING", "REMOVE_NON_PDF", "CHECK_INVALID_FILES",
            "NORMALIZE_FILES", "LIST_UNREADABLE_PDFS", "DELETE_UNREADABLE_PDFS",
            "DOWNLOAD_INVOICES_FROM_SIHOS", "CHECK_INVOICES", "VERIFY_INVOICE_CODE",
            "CHECK_INVOICE_NUMBER_ON_FILES", "CHECK_FOLDERS_WITH_EXTRA_TEXT",
            "NORMALIZE_DIR_NAMES", "CHECK_DIRS", "CATEGORIZE_INVOICES",
            "CHECK_REQUIRED_DOCS", "VERIFY_CUFE", "TAG_MISSING_CUFE",
            "ORGANIZE", "DOWNLOAD_DRIVE", "DOWNLOAD_MISSING_DOCS",
        }
        assert expected.issubset(set(_STAGE_HANDLERS.keys()))
        assert len(_STAGE_HANDLERS) == 21


# ---------------------------------------------------------------------------
# execute — dispatch and error handling
# ---------------------------------------------------------------------------

class TestExecute:
    async def test_unknown_stage_yields_error(self, minimal_institution, minimal_period):
        db = AsyncMock()
        lines = [line async for line in execute("UNKNOWN_STAGE", minimal_institution, minimal_period, db)]
        assert any("[ERROR]" in line and "desconocida" in line for line in lines)

    async def test_known_stage_yields_info_start_and_end(self, minimal_institution, minimal_period, tmp_path):
        db = AsyncMock()
        # Use REMOVE_NON_PDF with a tmp_path as stage so it runs without crashing
        inst = SimpleNamespace(**vars(minimal_institution))
        inst.base_path = str(tmp_path)
        period = SimpleNamespace(**vars(minimal_period))
        period.period_label = "."

        # Create the STAGE directory
        (tmp_path / "STAGE").mkdir()

        lines = [line async for line in execute("REMOVE_NON_PDF", inst, period, db)]
        assert any("[INFO] Iniciando etapa: REMOVE_NON_PDF" in line for line in lines)
        assert any("[INFO] Etapa completada: REMOVE_NON_PDF" in line for line in lines)

    async def test_stage_exception_yields_error_line(self, minimal_institution, minimal_period):
        db = AsyncMock()

        async def failing_stage(ctx):
            yield "[INFO] starting"
            raise ValueError("something went wrong")

        original = _STAGE_HANDLERS.get("LOAD_AND_PROCESS")
        _STAGE_HANDLERS["LOAD_AND_PROCESS"] = failing_stage
        try:
            lines = [line async for line in execute("LOAD_AND_PROCESS", minimal_institution, minimal_period, db)]
            assert any("[ERROR]" in line and "falló" in line for line in lines)
        finally:
            if original:
                _STAGE_HANDLERS["LOAD_AND_PROCESS"] = original


# ---------------------------------------------------------------------------
# Individual stage tests — STAGE dir absent guard
# ---------------------------------------------------------------------------

class TestStageGuards:
    """Each stage that requires STAGE dir should yield a WARN/ERROR when absent."""

    @pytest.mark.parametrize("stage_name", [
        "REMOVE_NON_PDF",
        "CHECK_INVALID_FILES",
        "NORMALIZE_FILES",
        "LIST_UNREADABLE_PDFS",
        "DELETE_UNREADABLE_PDFS",
        "CHECK_INVOICE_NUMBER_ON_FILES",
        "CHECK_FOLDERS_WITH_EXTRA_TEXT",
        "NORMALIZE_DIR_NAMES",
        "CHECK_DIRS",
        "CHECK_REQUIRED_DOCS",
        "VERIFY_CUFE",
        "TAG_MISSING_CUFE",
        "ORGANIZE",
    ])
    async def test_nonexistent_stage_dir_yields_warn_or_error(
        self, stage_name: str, minimal_institution, minimal_period, tmp_path
    ):
        db = AsyncMock()
        inst = SimpleNamespace(**vars(minimal_institution))
        inst.base_path = str(tmp_path / "nonexistent")
        period = SimpleNamespace(**vars(minimal_period))

        handler = _STAGE_HANDLERS[stage_name]
        from app.services.pipeline_runner import _build_context
        ctx = _build_context(inst, period, db, {})

        lines = [line async for line in handler(ctx)]
        assert any("[WARN]" in line or "[ERROR]" in line for line in lines), (
            f"Stage {stage_name!r} should warn or error when STAGE dir is absent"
        )


# ---------------------------------------------------------------------------
# REMOVE_NON_PDF — happy path with real tmp_path
# ---------------------------------------------------------------------------

class TestRemoveNonPdfStage:
    async def test_removes_non_pdf_file(self, tmp_path: Path, minimal_institution, minimal_period):
        from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS

        inst = SimpleNamespace(**vars(minimal_institution))
        inst.base_path = str(tmp_path)
        period = SimpleNamespace(**vars(minimal_period))
        period.period_label = "."

        stage_dir = tmp_path / "STAGE"
        stage_dir.mkdir()
        (stage_dir / "notes.txt").write_text("ignore me")
        (stage_dir / "keep.pdf").write_bytes(b"")

        db = AsyncMock()
        ctx = _build_context(inst, period, db, {})
        handler = _STAGE_HANDLERS["REMOVE_NON_PDF"]
        lines = [line async for line in handler(ctx)]

        assert any("1" in line and ("eliminado" in line.lower() or "no-pdf" in line.lower()) for line in lines)
        assert not (stage_dir / "notes.txt").exists()
        assert (stage_dir / "keep.pdf").exists()


# ---------------------------------------------------------------------------
# CATEGORIZE_INVOICES — mocked DB
# ---------------------------------------------------------------------------

class TestCategorizeInvoicesStage:
    async def test_yields_distribution(self, minimal_institution, minimal_period):
        from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS

        db = AsyncMock()
        with patch("app.services.pipeline_runner.InvoiceRepo") as MockRepo:
            MockRepo.return_value.get_service_type_distribution = AsyncMock(
                return_value={"URGENCIAS": 5, "GENERAL": 10}
            )
            ctx = _build_context(minimal_institution, minimal_period, db, {})
            handler = _STAGE_HANDLERS["CATEGORIZE_INVOICES"]
            lines = [line async for line in handler(ctx)]

        assert any("URGENCIAS" in line and "5" in line for line in lines)
        assert any("GENERAL" in line and "10" in line for line in lines)

    async def test_no_invoices_yields_warn(self, minimal_institution, minimal_period):
        from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS

        db = AsyncMock()
        with patch("app.services.pipeline_runner.InvoiceRepo") as MockRepo:
            MockRepo.return_value.get_service_type_distribution = AsyncMock(return_value={})
            ctx = _build_context(minimal_institution, minimal_period, db, {})
            handler = _STAGE_HANDLERS["CATEGORIZE_INVOICES"]
            lines = [line async for line in handler(ctx)]

        assert any("[WARN]" in line for line in lines)
