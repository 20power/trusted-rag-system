from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, KnowledgeChunk
from app.services.embedding_client import OpenAICompatibleEmbeddingClient
from app.services.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VectorIndexReport:
    indexed_chunks: int
    vector_size: int
    batch_count: int


def index_chunk_vectors(
    db: Session,
    settings: Settings,
    *,
    limit: int | None = None,
    embedding_client: OpenAICompatibleEmbeddingClient | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> VectorIndexReport:
    if not settings.embedding_is_configured:
        raise ValueError("Embedding Provider 尚未配置，不能建立向量索引")

    statement = (
        select(KnowledgeChunk, Document)
        .join(Document, Document.doc_id == KnowledgeChunk.doc_id)
        .where(
            Document.is_active.is_(True),
            Document.ingest_status == "indexed",
            Document.duplicate_of_doc_id.is_(None),
        )
        .order_by(KnowledgeChunk.chunk_id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    rows = list(db.execute(statement).all())
    if not rows:
        return VectorIndexReport(indexed_chunks=0, vector_size=0, batch_count=0)

    embedder = embedding_client or OpenAICompatibleEmbeddingClient(settings)
    store = vector_store or QdrantVectorStore(settings)
    indexed = 0
    batch_count = 0
    vector_size = 0
    batch_size = settings.embedding_batch_size
    total_batches = (len(rows) + batch_size - 1) // batch_size
    started_at = monotonic()
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = embedder.embed([chunk.search_text for chunk, _ in batch])
        if not vectors:
            continue
        if vector_size == 0:
            vector_size = len(vectors[0])
            store.ensure_collection(vector_size)
        records = []
        for (chunk, document), vector in zip(batch, vectors, strict=True):
            if len(vector) != vector_size:
                raise ValueError("Embedding 模型在批次之间返回了不同的向量维度")
            records.append(
                (
                    chunk.chunk_id,
                    vector,
                    {
                        "doc_id": chunk.doc_id,
                        "title": document.source_title,
                        "chunk_type": chunk.chunk_type,
                        "locator": chunk.locator,
                    },
                )
            )
        store.upsert(records)
        indexed += len(records)
        batch_count += 1
        if batch_count == 1 or batch_count % 10 == 0 or batch_count == total_batches:
            elapsed = max(monotonic() - started_at, 0.001)
            logger.info(
                "向量索引进度 batch=%s/%s chunks=%s/%s speed=%.1f chunks/s",
                batch_count,
                total_batches,
                indexed,
                len(rows),
                indexed / elapsed,
            )
    return VectorIndexReport(
        indexed_chunks=indexed,
        vector_size=vector_size,
        batch_count=batch_count,
    )
