"""Pydantic schemas for invoices and audit periods."""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class InvoiceListItem(BaseModel):
    """Enriched invoice row for the audit list view — all FK values pre-resolved."""
    model_config = {"from_attributes": True}

    id: int
    invoice_number: str
    patient_name: str
    institution_contract_id: int | None
    administrator_canonical: str | None   # resolved from institution_contract.administrator.canonical_name
    contract_type_name: str | None        # resolved from institution_contract.contract_type.name
    contract_canonical: str | None        # resolved from institution_contract.contract.canonical_name
    folder_status: str                    # resolved from folder_status.status
    folder_status_id: int
    service_type_code: str | None         # resolved from service_type.code
    service_type_id: int | None
    missing_file_count: int               # count of unresolved missing_files
    date: datetime.date


class InvoiceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    invoice_number: str
    date: datetime.date
    id_type: str
    id_number: str
    patient_name: str
    institution_contract_id: int | None
    service_type_id: int | None
    employee: str | None
    admission: str | None = None
    folder_status_id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class InvoiceFilter(BaseModel):
    institution_id: int | None = None
    period_id: int | None = None
    folder_status_id: int | None = None
    service_type_id: int | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 50


class InvoiceStatusUpdate(BaseModel):
    folder_status_id: int


class BatchStatusUpdate(BaseModel):
    invoice_ids: list[int]
    folder_status_id: int


class PeriodOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    institution_id: int
    date_from: datetime.date
    date_to: datetime.date
    period_label: str


class PeriodCreate(BaseModel):
    institution_id: int
    date_from: datetime.date
    date_to: datetime.date
    period_label: str
