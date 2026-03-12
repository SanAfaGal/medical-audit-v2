"""Pydantic schemas for audit findings."""
from pydantic import BaseModel


class FindingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    invoice_id: int
    doc_code: str
    comment: str


class FindingCreate(BaseModel):
    invoice_id: int
    doc_code: str
    comment: str = ""


class FindingDelete(BaseModel):
    invoice_id: int
    doc_code: str
