"""Pydantic schemas for business rules (service types, doc types, folder statuses)."""
from pydantic import BaseModel


class ServiceTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    code: str
    display_name: str
    keywords: str      # JSON string
    required_docs: str # JSON string
    sort_order: int
    is_active: bool


class ServiceTypeUpdate(BaseModel):
    display_name: str | None = None
    keywords: str | None = None       # JSON string
    required_docs: str | None = None  # JSON string
    sort_order: int | None = None
    is_active: bool | None = None


class DocTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    code: str
    label: str
    prefixes: str  # JSON string
    is_active: bool


class DocTypeUpdate(BaseModel):
    label: str | None = None
    prefixes: str | None = None  # JSON string
    is_active: bool | None = None


class FolderStatusDefOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    code: str
    label: str
    sort_order: int
