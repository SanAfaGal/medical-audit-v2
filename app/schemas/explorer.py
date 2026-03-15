"""Pydantic schemas para el explorador de archivos PDF."""
from __future__ import annotations

from pydantic import BaseModel


class FileNode(BaseModel):
    name: str
    path: str          # relativo al sandbox, ej: "DRIVE/sub/doc.pdf"
    is_dir: bool
    size: int | None = None   # bytes, None para carpetas


class ListResponse(BaseModel):
    entries: list[FileNode]
    current_path: str


class RenameRequest(BaseModel):
    institution_id: int
    period_id: int
    path: str
    new_name: str


class MoveRequest(BaseModel):
    institution_id: int
    period_id: int
    src: str
    dst_folder: str


class MergeRequest(BaseModel):
    institution_id: int
    period_id: int
    paths: list[str]          # PDFs a unir, en orden
    output_name: str          # nombre del PDF resultante


class SplitRequest(BaseModel):
    institution_id: int
    period_id: int
    path: str
    ranges: str | None = None  # "1-3, 5" o None para página a página


class ReorderRequest(BaseModel):
    institution_id: int
    period_id: int
    path: str
    page_order: list[int]     # índices 0-based en el nuevo orden


class DeleteRequest(BaseModel):
    institution_id: int
    period_id: int
    path: str


class OperationResult(BaseModel):
    ok: bool
    message: str
