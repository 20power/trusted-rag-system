from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.dependencies import DbSession
from app.db.models import Document, KnowledgeChunk
from app.schemas.documents import (
    DocumentList,
    DocumentRead,
    DocumentStats,
    ExtensionStat,
    StatusStat,
)

router = APIRouter()


@router.get("", response_model=DocumentList)
def list_documents(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    extension: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=200),
    active_only: bool = Query(default=True),
) -> DocumentList:
    filters = []
    if active_only:
        filters.append(Document.is_active.is_(True))
    if extension:
        normalized = extension.lower()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        filters.append(Document.extension == normalized)
    if status:
        filters.append(Document.ingest_status == status)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                Document.source_title.ilike(pattern),
                Document.original_filename.ilike(pattern),
                Document.doc_id.ilike(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    statement = (
        select(Document)
        .where(*filters)
        .order_by(Document.sequence_no.asc().nulls_last(), Document.original_filename.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(db.scalars(statement).all())
    return DocumentList(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=DocumentStats)
def document_stats(db: DbSession) -> DocumentStats:
    active_filter = Document.is_active.is_(True)
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    active = db.scalar(select(func.count()).select_from(Document).where(active_filter)) or 0
    duplicates = (
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(active_filter, Document.duplicate_of_doc_id.is_not(None))
        )
        or 0
    )
    total_bytes = (
        db.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0)).where(active_filter)) or 0
    )
    indexed_chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    extension_rows = db.execute(
        select(
            Document.extension,
            func.count(Document.id),
            func.coalesce(func.sum(Document.size_bytes), 0),
        )
        .where(active_filter)
        .group_by(Document.extension)
        .order_by(func.count(Document.id).desc())
    ).all()
    status_rows = db.execute(
        select(Document.ingest_status, func.count(Document.id))
        .where(active_filter)
        .group_by(Document.ingest_status)
        .order_by(func.count(Document.id).desc())
    ).all()
    return DocumentStats(
        total=total,
        active=active,
        duplicates=duplicates,
        total_bytes=total_bytes,
        indexed_chunks=indexed_chunks,
        by_extension=[
            ExtensionStat(extension=row[0], count=row[1], total_bytes=row[2])
            for row in extension_rows
        ],
        by_status=[StatusStat(status=row[0], count=row[1]) for row in status_rows],
    )


@router.get("/{doc_id}", response_model=DocumentRead)
def get_document(doc_id: str, db: DbSession) -> Document:
    document = db.scalar(select(Document).where(Document.doc_id == doc_id))
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document
