"""Pydantic schemas for hospitals, admins, and contracts."""

from pydantic import BaseModel


class HospitalCreate(BaseModel):
    key: str
    name: str
    nit: str
    invoice_prefix: str
    sihos_url: str | None = None
    sihos_code: str | None = None
    sihos_user: str | None = None
    sihos_password: str | None = None  # plaintext — encrypted before DB insert
    drive_credentials_json: str | None = None  # JSON string — encrypted before DB insert
    base_path: str | None = None


class HospitalUpdate(BaseModel):
    name: str | None = None
    nit: str | None = None
    invoice_prefix: str | None = None
    sihos_url: str | None = None
    sihos_code: str | None = None
    sihos_user: str | None = None
    sihos_password: str | None = None
    drive_credentials_json: str | None = None
    base_path: str | None = None


class HospitalOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    key: str
    name: str
    nit: str
    invoice_prefix: str
    sihos_url: str | None
    sihos_code: str | None
    sihos_user: str | None
    base_path: str | None
    # NOTE: sihos_password_enc and drive_credentials_json_enc are never exposed


class AdminOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    raw_value: str
    canonical_value: str | None


class AdminUpdate(BaseModel):
    canonical_value: str | None


class ContractOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    raw_value: str
    canonical_value: str | None


class ContractUpdate(BaseModel):
    canonical_value: str | None
