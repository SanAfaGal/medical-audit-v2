"""Tests for app/services/billing.py — pure pandas tests + ingest with mocked repos."""
from __future__ import annotations

import io
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.billing import _normalize, load_excel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_excel_bytes(**overrides) -> bytes:
    """Create a minimal valid SIHOS Excel as bytes."""
    row = {
        "FACTURA": "FV123456",
        "FECHA": "2024-01-15",
        "DOCUMENTO": "CC",
        "NUMERO": "12345678",
        "PACIENTE": "Juan Perez",
        "ADMINISTRADORA": "NUEVA EPS",
        "CONTRATO": "C001",
        "SERVICIO": "URGENCIAS",
        "OPERARIO": "Dr. Lopez",
        **overrides,
    }
    df = pd.DataFrame([row])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# load_excel
# ---------------------------------------------------------------------------

class TestLoadExcel:
    def test_reads_all_expected_columns(self):
        data = load_excel(_make_excel_bytes())
        expected = {"FACTURA", "FECHA", "DOCUMENTO", "NUMERO", "PACIENTE",
                    "ADMINISTRADORA", "CONTRATO", "SERVICIO", "OPERARIO"}
        assert set(data.columns) == expected

    def test_drops_extra_columns(self):
        # Add an extra column to the Excel
        row = {
            "FACTURA": "FV1", "FECHA": "2024-01-01", "DOCUMENTO": "CC",
            "NUMERO": "1", "PACIENTE": "P", "ADMINISTRADORA": "A",
            "CONTRATO": "C", "SERVICIO": "S", "OPERARIO": "O",
            "EXTRA_COLUMN": "should_be_dropped",
        }
        df = pd.DataFrame([row])
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        result = load_excel(buf.getvalue())
        assert "EXTRA_COLUMN" not in result.columns

    def test_missing_columns_are_absent_not_error(self):
        # Excel with only some columns
        df = pd.DataFrame([{"FACTURA": "FV1", "FECHA": "2024-01-01"}])
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        result = load_excel(buf.getvalue())
        assert "FACTURA" in result.columns
        assert "SERVICIO" not in result.columns  # not present → not in result


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_strips_and_uppercases_factura(self):
        df = pd.DataFrame([{
            "FACTURA": "  fv123  ",
            "FECHA": "2024-01-15",
            "ADMINISTRADORA": "EPS",
        }])
        result = _normalize(df)
        assert result["FACTURA"].iloc[0] == "FV123"

    def test_drops_rows_with_empty_factura(self):
        df = pd.DataFrame([
            {"FACTURA": "FV1", "FECHA": "2024-01-15", "ADMINISTRADORA": "EPS"},
            {"FACTURA": "",    "FECHA": "2024-01-15", "ADMINISTRADORA": "EPS"},
            {"FACTURA": None,  "FECHA": "2024-01-15", "ADMINISTRADORA": "EPS"},
        ])
        result = _normalize(df)
        assert len(result) == 1
        assert result["FACTURA"].iloc[0] == "FV1"

    def test_drops_rows_with_null_administradora(self):
        df = pd.DataFrame([
            {"FACTURA": "FV1", "FECHA": "2024-01-15", "ADMINISTRADORA": "EPS"},
            {"FACTURA": "FV2", "FECHA": "2024-01-15", "ADMINISTRADORA": None},
        ])
        result = _normalize(df)
        assert len(result) == 1

    def test_parses_fecha_to_date(self):
        df = pd.DataFrame([{
            "FACTURA": "FV1",
            "FECHA": "2024-03-20",
            "ADMINISTRADORA": "EPS",
        }])
        result = _normalize(df)
        assert result["FECHA"].iloc[0] == datetime.date(2024, 3, 20)

    def test_invalid_fecha_becomes_nat(self):
        df = pd.DataFrame([{
            "FACTURA": "FV1",
            "FECHA": "not-a-date",
            "ADMINISTRADORA": "EPS",
        }])
        result = _normalize(df)
        assert pd.isna(result["FECHA"].iloc[0])

    def test_returns_copy_does_not_mutate_input(self):
        df = pd.DataFrame([{
            "FACTURA": "  fv1  ",
            "FECHA": "2024-01-01",
            "ADMINISTRADORA": "EPS",
        }])
        original_factura = df["FACTURA"].iloc[0]
        _normalize(df)
        assert df["FACTURA"].iloc[0] == original_factura


# ---------------------------------------------------------------------------
# ingest — mocked repos
# ---------------------------------------------------------------------------

class TestIngest:
    """Integration-lite tests for billing.ingest using AsyncMock."""

    def _make_institution(self, name="Hospital Test"):
        return SimpleNamespace(id=1, name=name)

    def _make_admin(self, canonical=None):
        return SimpleNamespace(id=10, canonical_admin=canonical)

    def _make_service(self, service_type_id=99):
        return SimpleNamespace(id=20, service_type_id=service_type_id)

    def _make_contract(self, canonical=None):
        return SimpleNamespace(id=30, canonical_contract=canonical)

    def _make_folder_status(self):
        return SimpleNamespace(id=2)

    def _make_service_type(self, st_id=99):
        return SimpleNamespace(id=st_id)

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    async def test_inserted_count_for_mapped_admin(self, mock_db):
        from app.services.billing import ingest

        institution = self._make_institution()
        default_st = self._make_service_type(99)
        default_fs = self._make_folder_status()
        admin = self._make_admin(canonical="EPS NUEVA")
        service = self._make_service(service_type_id=99)
        contract = self._make_contract(canonical="C001")

        with (
            patch("app.services.billing.RulesRepo") as MockRulesRepo,
            patch("app.services.billing.InstitutionRepo") as MockInstRepo,
            patch("app.services.billing.InvoiceRepo") as MockInvRepo,
        ):
            MockRulesRepo.return_value.get_service_type_by_code = AsyncMock(return_value=default_st)
            MockRulesRepo.return_value.get_folder_status_by_status = AsyncMock(return_value=default_fs)
            MockInstRepo.return_value.upsert_admin = AsyncMock(return_value=admin)
            MockInstRepo.return_value.upsert_contract = AsyncMock(return_value=contract)
            MockInstRepo.return_value.upsert_service = AsyncMock(return_value=service)
            MockInvRepo.return_value.upsert_invoice = AsyncMock(return_value=SimpleNamespace(id=1))
            mock_db.commit = AsyncMock()

            result = await ingest(_make_excel_bytes(), institution, period_id=1, db=mock_db)

        assert result["inserted"] == 1
        assert result["skipped"] == 0

    async def test_skips_row_when_admin_not_mapped(self, mock_db):
        from app.services.billing import ingest

        institution = self._make_institution()
        default_st = self._make_service_type()
        default_fs = self._make_folder_status()
        admin = self._make_admin(canonical=None)  # not mapped

        with (
            patch("app.services.billing.RulesRepo") as MockRulesRepo,
            patch("app.services.billing.InstitutionRepo") as MockInstRepo,
            patch("app.services.billing.InvoiceRepo"),
        ):
            MockRulesRepo.return_value.get_service_type_by_code = AsyncMock(return_value=default_st)
            MockRulesRepo.return_value.get_folder_status_by_status = AsyncMock(return_value=default_fs)
            MockInstRepo.return_value.upsert_admin = AsyncMock(return_value=admin)
            mock_db.commit = AsyncMock()

            result = await ingest(_make_excel_bytes(), institution, period_id=1, db=mock_db)

        assert result["inserted"] == 0
        assert result["skipped"] == 1
        assert "NUEVA EPS" in result["unknown_admins"]

    async def test_unknown_service_recorded(self, mock_db):
        from app.services.billing import ingest

        institution = self._make_institution()
        default_st = self._make_service_type(st_id=99)  # GENERAL id
        default_fs = self._make_folder_status()
        admin = self._make_admin(canonical="EPS NUEVA")
        # service still at default (GENERAL)
        service = self._make_service(service_type_id=99)

        with (
            patch("app.services.billing.RulesRepo") as MockRulesRepo,
            patch("app.services.billing.InstitutionRepo") as MockInstRepo,
            patch("app.services.billing.InvoiceRepo") as MockInvRepo,
        ):
            MockRulesRepo.return_value.get_service_type_by_code = AsyncMock(return_value=default_st)
            MockRulesRepo.return_value.get_folder_status_by_status = AsyncMock(return_value=default_fs)
            MockInstRepo.return_value.upsert_admin = AsyncMock(return_value=admin)
            MockInstRepo.return_value.upsert_contract = AsyncMock(return_value=self._make_contract("C"))
            MockInstRepo.return_value.upsert_service = AsyncMock(return_value=service)
            MockInvRepo.return_value.upsert_invoice = AsyncMock(return_value=SimpleNamespace(id=1))
            mock_db.commit = AsyncMock()

            result = await ingest(_make_excel_bytes(), institution, period_id=1, db=mock_db)

        assert "URGENCIAS" in result["unknown_services"]

    async def test_raises_if_default_service_type_missing(self, mock_db):
        from app.services.billing import ingest

        with patch("app.services.billing.RulesRepo") as MockRulesRepo:
            MockRulesRepo.return_value.get_service_type_by_code = AsyncMock(return_value=None)
            MockRulesRepo.return_value.get_folder_status_by_status = AsyncMock(return_value=SimpleNamespace(id=1))

            with pytest.raises(RuntimeError, match="GENERAL"):
                await ingest(_make_excel_bytes(), self._make_institution(), period_id=1, db=mock_db)
