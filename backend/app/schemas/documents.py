from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: str
    source_title: str
    original_filename: str
    relative_path: str
    extension: str
    mime_type: str
    file_signature: str
    size_bytes: int
    sha256: str
    sequence_no: int | None
    year_hint: int | None
    publisher: str | None
    publish_date: date | None
    document_no: str | None
    version_status: str
    duplicate_of_doc_id: str | None
    is_active: bool
    ingest_status: str
    parser_version: str | None
    parsed_artifact_path: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int
    page: int
    page_size: int


class ExtensionStat(BaseModel):
    extension: str
    count: int
    total_bytes: int


class StatusStat(BaseModel):
    status: str
    count: int


class DocumentStats(BaseModel):
    total: int
    active: int
    duplicates: int
    total_bytes: int
    indexed_chunks: int
    by_extension: list[ExtensionStat]
    by_status: list[StatusStat]


class ScanResponse(BaseModel):
    run_id: str
    discovered_files: int
    new_files: int
    updated_files: int
    duplicate_files: int
    failed_files: int
    manifest_path: str
    extension_counts: dict[str, int]
    total_bytes: int


class ParseResponse(BaseModel):
    doc_id: str
    status: str
    artifact_path: str | None = None
    chunk_count: int = 0
    message: str | None = None


class BatchParseRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)
    extensions: list[str] | None = None


class BatchParseResponse(BaseModel):
    requested: int
    parsed: int
    failed: int
    results: list[ParseResponse]


class BatchIndexRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class IndexResponse(BaseModel):
    doc_id: str
    status: str
    chunk_count: int = 0
    message: str | None = None


class BatchIndexResponse(BaseModel):
    requested: int
    indexed: int
    failed: int
    results: list[IndexResponse]
