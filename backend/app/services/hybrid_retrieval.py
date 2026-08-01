from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, KnowledgeChunk
from app.services.embedding_client import (
    EmbeddingClientError,
    OpenAICompatibleEmbeddingClient,
)
from app.services.retrieval import SearchHit, search_chunks
from app.services.vector_store import QdrantVectorStore, VectorStoreError


@dataclass(slots=True)
class RetrievalResult:
    hits: list[SearchHit]
    mode: str
    warnings: list[str] = field(default_factory=list)


def _fusion_weights(question: str) -> tuple[float, float]:
    return 0.55, 0.45


def _uses_lexical_policy(
    question: str,
    lexical_hits: list[SearchHit] | None = None,
) -> bool:
    lowered = question.lower()
    explicitly_exact = (
        "pdf" in lowered
        or "excel" in lowered
        or "xlsx" in lowered
        or "xls附件" in lowered
    )
    if explicitly_exact:
        return True
    if not lexical_hits:
        return False
    exact_extensions = (".pdf", ".xls", ".xlsx")
    sample = lexical_hits[: min(5, len(lexical_hits))]
    return all(hit.source_file.lower().endswith(exact_extensions) for hit in sample)


def _load_vector_hits(
    db: Session,
    chunk_ids: list[str],
) -> dict[str, SearchHit]:
    if not chunk_ids:
        return {}
    rows = db.execute(
        select(KnowledgeChunk, Document)
        .join(Document, Document.doc_id == KnowledgeChunk.doc_id)
        .where(
            KnowledgeChunk.chunk_id.in_(chunk_ids),
            Document.is_active.is_(True),
            Document.ingest_status == "indexed",
            Document.duplicate_of_doc_id.is_(None),
        )
    ).all()
    hits: dict[str, SearchHit] = {}
    for chunk, document in rows:
        try:
            metadata = json.loads(chunk.metadata_json)
        except json.JSONDecodeError:
            metadata = {}
        hits[chunk.chunk_id] = SearchHit(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            title=document.source_title,
            source_file=document.original_filename,
            locator=chunk.locator,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            score=0.0,
            metadata=metadata,
        )
    return hits


def retrieve_chunks(
    db: Session,
    question: str,
    *,
    settings: Settings,
    top_k: int = 5,
    embedding_client: OpenAICompatibleEmbeddingClient | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> RetrievalResult:
    candidate_count = max(top_k, settings.hybrid_candidate_count)
    lexical_hits = search_chunks(
        db,
        question,
        top_k=candidate_count,
    )
    if not settings.embedding_is_configured:
        return RetrievalResult(hits=lexical_hits[:top_k], mode="lexical")
    if _uses_lexical_policy(question, lexical_hits):
        return RetrievalResult(hits=lexical_hits[:top_k], mode="lexical_policy")

    embedder = embedding_client or OpenAICompatibleEmbeddingClient(settings)
    store = vector_store or QdrantVectorStore(settings)
    try:
        query_vector = embedder.embed([question])[0]
        requested_doc_ids = None
        if "《" in question and "》" in question and lexical_hits:
            requested_doc_ids = list(dict.fromkeys(hit.doc_id for hit in lexical_hits))
        vector_matches = store.search(
            query_vector,
            limit=candidate_count,
            doc_ids=requested_doc_ids,
        )
    except (EmbeddingClientError, VectorStoreError, IndexError) as exc:
        return RetrievalResult(
            hits=lexical_hits[:top_k],
            mode="lexical_fallback",
            warnings=[f"混合检索不可用，已降级为离线稀疏检索：{exc}"],
        )

    vector_hit_map = _load_vector_hits(
        db,
        [match.chunk_id for match in vector_matches],
    )
    hit_map = {hit.chunk_id: hit for hit in lexical_hits}
    hit_map.update(vector_hit_map)

    fused_scores: dict[str, float] = {}
    lexical_weight, vector_weight = _fusion_weights(question)
    for rank, hit in enumerate(lexical_hits, start=1):
        fused_scores[hit.chunk_id] = fused_scores.get(hit.chunk_id, 0.0) + (
            lexical_weight / (60 + rank)
        )
    for rank, match in enumerate(vector_matches, start=1):
        if match.chunk_id in hit_map:
            fused_scores[match.chunk_id] = fused_scores.get(match.chunk_id, 0.0) + (
                vector_weight / (60 + rank)
            )

    ordered_ids = sorted(
        fused_scores,
        key=lambda chunk_id: (-fused_scores[chunk_id], chunk_id),
    )
    results: list[SearchHit] = []
    for chunk_id in ordered_ids[:top_k]:
        hit = hit_map[chunk_id]
        hit.score = round(fused_scores[chunk_id] * 1000, 6)
        results.append(hit)
    return RetrievalResult(hits=results, mode="hybrid")
