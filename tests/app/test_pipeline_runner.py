"""Tests for app/services/pipeline_runner.py — dispatch + stage error handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS, execute


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_all_keys_present(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {}, "/data")
        for key in ("institution", "period", "db", "base_path", "drive_path", "stage_path", "audit_path"):
            assert key in ctx

    def test_paths_derived_from_base(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {}, "/data")
        base = Path("/data") / minimal_institution.name / minimal_period.period_label
        assert ctx["base_path"] == base
        assert ctx["drive_path"] == base / "DRIVE"
        assert ctx["stage_path"] == base / "STAGE"
        assert ctx["audit_path"] == base / "AUDIT"

    def test_extra_keys_merged(self, minimal_institution, minimal_period):
        db = AsyncMock()
        ctx = _build_context(minimal_institution, minimal_period, db, {"invoice_numbers": ["X"]}, "/data")
        assert ctx["invoice_numbers"] == ["X"]


# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------


class TestStageRegistry:
    def test_all_stages_registered(self):
        expected = {
            "LOAD_AND_PROCESS",
            "RECATEGORIZE_SERVICES",
            "RUN_STAGING",
            "CHECK_NESTED_FOLDERS",
            "REMOVE_NON_PDF",
            "NORMALIZE_FILES",
            "LIST_UNREADABLE_PDFS",
            "DELETE_UNREADABLE_PDFS",
            "DOWNLOAD_INVOICES_FROM_SIHOS",
            "DOWNLOAD_MEDICATION_SHEETS",
            "CHECK_INVOICES",
            "VERIFY_INVOICE_CODE",
            "CHECK_INVOICE_NUMBER_ON_FILES",
            "CHECK_FOLDERS_WITH_EXTRA_TEXT",
            "NORMALIZE_DIR_NAMES",
            "CHECK_DIRS",
            "MARK_UNKNOWN_DIRS",
            "CHECK_REQUIRED_DOCS",
            "REVISAR_SOBRANTES",
            "VERIFY_CUFE",
            "ORGANIZE",
            "DOWNLOAD_DRIVE",
            "DOWNLOAD_MISSING_DOCS",
        }
        assert expected == set(_STAGE_HANDLERS.keys())


# ---------------------------------------------------------------------------
# execute — dispatch and error handling
# ---------------------------------------------------------------------------


class TestExecute:
    async def test_unknown_stage_yields_error(self, minimal_institution, minimal_period):
        db = AsyncMock()
        lines = [line async for line in execute("UNKNOWN_STAGE", minimal_institution, minimal_period, db)]
        assert any("[ERROR]" in line and "desconocida" in line for line in lines)

    async def test_known_stage_runs_without_error(self, minimal_institution, minimal_period, tmp_path):
        """REMOVE_NON_PDF with empty STAGE should complete cleanly (no ERROR lines)."""
        inst = SimpleNamespace(**vars(minimal_institution))
        period = SimpleNamespace(**vars(minimal_period))
        period.period_label = "."

        # Create the STAGE directory at the path _build_context will resolve
        stage_dir = tmp_path / inst.name / "STAGE"
        stage_dir.mkdir(parents=True)

        db = AsyncMock()
        fake_settings = SimpleNamespace(audit_data_root=str(tmp_path))
        with patch("app.services.pipeline_runner.RulesRepo") as mock_repo:
            mock_repo.return_value.get_system_settings = AsyncMock(return_value=fake_settings)
            lines = [line async for line in execute("REMOVE_NON_PDF", inst, period, db)]

        assert any("[INFO]" in line for line in lines)
        assert not any("[ERROR]" in line for line in lines)

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

    @pytest.mark.parametrize(
        "stage_name",
        [
            "REMOVE_NON_PDF",
            "NORMALIZE_FILES",
            "LIST_UNREADABLE_PDFS",
            "DELETE_UNREADABLE_PDFS",
            "CHECK_INVOICE_NUMBER_ON_FILES",
            "CHECK_FOLDERS_WITH_EXTRA_TEXT",
            "NORMALIZE_DIR_NAMES",
            "CHECK_DIRS",
            "CHECK_REQUIRED_DOCS",
            "VERIFY_CUFE",
            "ORGANIZE",
        ],
    )
    async def test_nonexistent_stage_dir_yields_warn_or_error(
        self, stage_name: str, minimal_institution, minimal_period, tmp_path
    ):
        db = AsyncMock()
        inst = SimpleNamespace(**vars(minimal_institution))
        period = SimpleNamespace(**vars(minimal_period))

        handler = _STAGE_HANDLERS[stage_name]
        from app.services.pipeline_runner import _build_context

        # audit_data_root points to tmp_path; STAGE subdir is never created → path absent
        ctx = _build_context(inst, period, db, {}, str(tmp_path))

        lines = [line async for line in handler(ctx)]
        assert any("[WARN]" in line or "[ERROR]" in line for line in lines), (
            f"Stage {stage_name!r} should warn or error when STAGE dir is absent"
        )


# ---------------------------------------------------------------------------
# REMOVE_NON_PDF — happy path with real tmp_path
# ---------------------------------------------------------------------------


class TestRemoveNonPdfStage:
    async def test_scans_non_pdf_files(self, tmp_path: Path, minimal_institution, minimal_period):
        from app.services.pipeline_runner import _build_context, _STAGE_HANDLERS

        inst = SimpleNamespace(**vars(minimal_institution))
        period = SimpleNamespace(**vars(minimal_period))
        period.period_label = "."

        # _build_context resolves: audit_data_root / inst.name / period_label / "STAGE"
        # With period_label="." → audit_data_root / inst.name / "STAGE"
        stage_dir = tmp_path / inst.name / "STAGE"
        stage_dir.mkdir(parents=True)
        (stage_dir / "notes.txt").write_text("ignore me")
        (stage_dir / "valid.pdf").write_bytes(b"%PDF-1.4 test")  # minimal valid header

        db = AsyncMock()
        ctx = _build_context(inst, period, db, {}, str(tmp_path))
        handler = _STAGE_HANDLERS["REMOVE_NON_PDF"]
        lines = [line async for line in handler(ctx)]

        # Stage is scan-only: files are NOT deleted, [DATA] is emitted for UI review
        assert any("1" in line and "no-pdf" in line.lower() for line in lines)
        assert (stage_dir / "notes.txt").exists()  # scan only — no deletion
        assert (stage_dir / "valid.pdf").exists()
