"""Pydantic schemas for invoices."""
from pydantic import BaseModel


class InvoiceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    factura: str
    fecha: str | None
    paciente: str | None
    administradora: str | None
    contrato: str | None
    ruta: str | None
    folder_status: str
    nota: str
    service_type_id: int | None
    finding_codes: list[str] = []  # populated by repo join


class InvoiceFilter(BaseModel):
    hospital_key: str
    period_code: str
    folder_status: str | None = None
    service_type_id: int | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 50


class InvoiceStatusUpdate(BaseModel):
    folder_status: str


class InvoiceNotaUpdate(BaseModel):
    nota: str


class BatchStatusUpdate(BaseModel):
    invoice_ids: list[int]
    folder_status: str
