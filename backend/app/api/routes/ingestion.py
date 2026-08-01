from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import AppSettings, DbSession
from app.core.config import Settings
from app.db.models import Document
from app.schemas.documents import (
    BatchIndexRequest,
    BatchIndexResponse,
    BatchParseRequest,
    BatchParseResponse,
    IndexResponse,
    ParseResponse,
    ScanResponse,
)
from app.services.indexing import index_document
from app.services.manifest import scan_source_directory
from app.services.parsers import parse_document

router = APIRouter()


@router.post("/scan", response_model=ScanResponse)
def scan(
    db: DbSession,
    settings: AppSettings,
) -> ScanResponse:
    try:
        return ScanResponse.model_validate(
            scan_source_directory(db, settings),
            from_attributes=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_one(document: Document, db: Session, settings: Settings) -> ParseResponse:
    document.ingest_status = "parsing"
    document.error_code = None
    document.error_message = None
    db.commit()
    try:
        artifact_path = parse_document(document, settings)
        document.parsed_artifact_path = str(artifact_path)
        document.parser_version = "0.1.0"
        db.commit()
        chunk_count = index_document(document, db)
        return ParseResponse(
            doc_id=document.doc_id,
            status="indexed",
            artifact_path=str(artifact_path),
            chunk_count=chunk_count,
        )
    except Exception as exc:
        document.ingest_status = "failed"
        document.error_code = type(exc).__name__
        document.error_message = str(exc)[:4000]
        db.commit()
        return ParseResponse(
            doc_id=document.doc_id,
            status="failed",
            message=str(exc),
        )


@router.post("/parse/{doc_id}", response_model=ParseResponse)
def parse_single(
    doc_id: str,
    db: DbSession,
    settings: AppSettings,
) -> ParseResponse:
    document = db.scalar(
        select(Document).where(Document.doc_id == doc_id, Document.is_active.is_(True))
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _parse_one(document, db, settings)


@router.post("/parse-batch", response_model=BatchParseResponse)
def parse_batch(
    request: BatchParseRequest,
    db: DbSession,
    settings: AppSettings,
) -> BatchParseResponse:
    filters = [
        Document.is_active.is_(True),
        Document.ingest_status.in_(["discovered", "failed"]),
    ]
    if request.extensions:
        normalized = [item if item.startswith(".") else f".{item}" for item in request.extensions]
        filters.append(Document.extension.in_([item.lower() for item in normalized]))
    documents = list(
        db.scalars(
            select(Document)
            .where(*filters)
            .order_by(Document.sequence_no.asc().nulls_last())
            .limit(request.limit)
        ).all()
    )
    results = [_parse_one(document, db, settings) for document in documents]
    return BatchParseResponse(
        requested=len(documents),
        parsed=sum(item.status == "indexed" for item in results),
        failed=sum(item.status == "failed" for item in results),
        results=results,
    )


def _index_one(document: Document, db: Session) -> IndexResponse:
    try:
        chunk_count = index_document(document, db)
        return IndexResponse(
            doc_id=document.doc_id,
            status="indexed",
            chunk_count=chunk_count,
        )
    except Exception as exc:
        document.ingest_status = "failed"
        document.error_code = type(exc).__name__
        document.error_message = str(exc)[:4000]
        db.commit()
        return IndexResponse(
            doc_id=document.doc_id,
            status="failed",
            message=str(exc),
        )


@router.post("/index/{doc_id}", response_model=IndexResponse)
def index_single(doc_id: str, db: DbSession) -> IndexResponse:
    document = db.scalar(
        select(Document).where(Document.doc_id == doc_id, Document.is_active.is_(True))
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _index_one(document, db)


@router.post("/index-batch", response_model=BatchIndexResponse)
def index_batch(request: BatchIndexRequest, db: DbSession) -> BatchIndexResponse:
    documents = list(
        db.scalars(
            select(Document)
            .where(
                Document.is_active.is_(True),
                Document.ingest_status.in_(["parsed", "indexed"]),
                Document.parsed_artifact_path.is_not(None),
            )
            .order_by(Document.sequence_no.asc().nulls_last())
            .limit(request.limit)
        ).all()
    )
    results = [_index_one(document, db) for document in documents]
    return BatchIndexResponse(
        requested=len(documents),
        indexed=sum(item.status == "indexed" for item in results),
        failed=sum(item.status == "failed" for item in results),
        results=results,
    )
