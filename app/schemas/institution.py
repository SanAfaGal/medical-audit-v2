"""Pydantic schemas for institutions, admins, contracts, and services."""
from pydantic import BaseModel


class InstitutionCreate(BaseModel):
    name: str                           # internal unique key, e.g. "SANTA_LUCIA"
    display_name: str                   # human-readable, e.g. "Hospital Santa Lucia"
    nit: str
    invoice_id_prefix: str
    sihos_base_url: str | None = None
    sihos_doc_code: str | None = None
    sihos_user: str | None = None
    sihos_password: str | None = None   # plaintext — encrypted before DB insert
    base_path: str | None = None
    drive_credentials_json: str | None = None   # plaintext JSON — encrypted before DB insert


class InstitutionUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    nit: str | None = None
    invoice_id_prefix: str | None = None
    sihos_base_url: str | None = None
    sihos_doc_code: str | None = None
    sihos_user: str | None = None
    sihos_password: str | None = None   # plaintext — encrypted before DB insert
    base_path: str | None = None
    drive_credentials_json: str | None = None   # plaintext JSON — encrypted before DB insert


class InstitutionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    display_name: str
    nit: str
    invoice_id_prefix: str
    sihos_base_url: str | None
    sihos_doc_code: str | None
    sihos_user: str | None
    base_path: str | None
    # NOTE: sihos_password and drive_credentials_enc are never exposed


class AdminOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    institution_id: int
    type: str | None
    raw_admin: str
    canonical_admin: str | None


class AdminUpdate(BaseModel):
    canonical_admin: str | None = None
    type: str | None = None


class ContractOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    institution_id: int
    raw_contract: str
    canonical_contract: str | None


class ContractUpdate(BaseModel):
    canonical_contract: str | None = None


class ServiceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    institution_id: int
    raw_service: str
    service_type_id: int


class ServiceUpdate(BaseModel):
    service_type_id: int
