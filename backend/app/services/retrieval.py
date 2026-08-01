from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, KnowledgeChunk

BOOK_TITLE_PATTERN = re.compile(r"《([^》]{2,100})》")
NORMALIZE_PATTERN = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
FORMAT_QUALIFIER_PATTERN = re.compile(
    r"[（(]\s*(?:pdf|word|excel|docx?|xlsx?)\s*[)）]",
    re.IGNORECASE,
)


def _requested_extensions(question: str) -> tuple[str, ...] | None:
    lowered = question.lower()
    if "pdf" in lowered:
        return (".pdf",)
    if "excel" in lowered or "xlsx" in lowered or "xls附件" in lowered:
        return (".xls", ".xlsx")
    if "word" in lowered or "docx" in lowered or "doc附件" in lowered:
        return (".doc", ".docx")
    return None


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    title: str
    source_file: str
    locator: str
    chunk_type: str
    content: str
    score: float
    metadata: dict[str, object]

    def to_evidence(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "source_file": self.source_file,
            "locator": self.locator,
            "chunk_type": self.chunk_type,
            "content": self.content,
            "score": round(self.score, 4),
            "metadata": self.metadata,
        }


def normalize_text(text: str) -> str:
    return NORMALIZE_PATTERN.sub("", text.lower())


def character_ngrams(text: str, size: int = 2) -> set[str]:
    normalized = normalize_text(text)
    if len(normalized) <= size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _score(
    question: str,
    *,
    title: str,
    search_text: str,
    content: str,
    requested_title: str | None,
) -> float:
    query_grams = character_ngrams(question)
    text_grams = character_ngrams(search_text)
    if not query_grams or not text_grams:
        return 0.0

    overlap = query_grams & text_grams
    coverage = len(overlap) / len(query_grams)
    precision = len(overlap) / min(len(text_grams), 300)
    score = coverage * 5.0 + precision
    content_grams = character_ngrams(content)
    if content_grams:
        score += 3.0 * len(query_grams & content_grams) / len(query_grams)

    normalized_question = normalize_text(question)
    normalized_title = normalize_text(title)
    normalized_content = normalize_text(content)
    if requested_title:
        requested_grams = character_ngrams(requested_title)
        title_grams = character_ngrams(title)
        title_coverage = (
            len(requested_grams & title_grams) / len(requested_grams)
            if requested_grams
            else 0.0
        )
        score += 12.0 * title_coverage
        if title_coverage >= 0.9:
            score += 5.0
        if normalize_text(requested_title) in normalized_title:
            score += 5.0
    if normalized_title and normalized_title in normalized_question:
        score += 3.0

    query_numbers = set(NUMBER_PATTERN.findall(question))
    content_numbers = set(NUMBER_PATTERN.findall(content))
    if query_numbers:
        score += 1.5 * len(query_numbers & content_numbers) / len(query_numbers)

    if normalized_content and normalized_content in normalized_question:
        score += 6.0

    if "候选表述：" in question:
        candidate_text = question.split("候选表述：", 1)[1]
        seen_candidates: set[str] = set()
        for candidate in re.split(r"[；;]", candidate_text):
            normalized_candidate = normalize_text(candidate)
            if normalized_candidate in seen_candidates:
                continue
            seen_candidates.add(normalized_candidate)
            if (
                len(normalized_candidate) >= 8
                and normalized_content
                and (
                    normalized_candidate in normalized_content
                    or normalized_content in normalized_candidate
                )
            ):
                score += 8.0

    numeric_intent = any(
        term in question for term in ("数值", "多少", "余额", "收入", "比例", "金额", "合计")
    )
    cell_values = [
        segment.split("=", 1)[1].strip()
        for segment in content.split("；")
        if "=" in segment and segment.split("=", 1)[1].strip()
    ]
    has_numeric_cell = any(NUMBER_PATTERN.fullmatch(value) for value in cell_values)
    if numeric_intent:
        score += 2.0 if has_numeric_cell else -3.0
    for value in cell_values:
        normalized_value = normalize_text(value)
        if (
            len(normalized_value) >= 2
            and normalized_value != normalized_title
            and normalized_value in normalized_question
        ):
            score += 3.0
    return score


def _candidate_document_ids(
    db: Session,
    requested_title: str,
    *,
    question: str | None = None,
    extensions: tuple[str, ...] | None = None,
    limit: int = 8,
) -> list[str]:
    cleaned_title = FORMAT_QUALIFIER_PATTERN.sub("", requested_title)
    requested_normalized = normalize_text(cleaned_title)
    requested_grams = character_ngrams(cleaned_title)
    context = question or ""
    context = context.replace(f"《{requested_title}》", "")
    context_grams = character_ngrams(context)
    if not requested_grams:
        return []

    content_statement = (
        select(KnowledgeChunk.doc_id)
        .join(Document, Document.doc_id == KnowledgeChunk.doc_id)
        .where(KnowledgeChunk.search_text.ilike(f"%{cleaned_title}%"))
        .distinct()
        .limit(100)
    )
    if extensions:
        content_statement = content_statement.where(Document.extension.in_(extensions))
    content_matches = set(db.scalars(content_statement).all())

    scored: list[tuple[float, str]] = []
    document_statement = select(Document).where(
            Document.is_active.is_(True),
            Document.ingest_status == "indexed",
            Document.duplicate_of_doc_id.is_(None),
        )
    if extensions:
        document_statement = document_statement.where(Document.extension.in_(extensions))
    documents = db.scalars(document_statement).all()
    for document in documents:
        combined = f"{document.source_title} {document.original_filename}"
        combined_normalized = normalize_text(combined)
        combined_grams = character_ngrams(combined)
        overlap = requested_grams & combined_grams
        coverage = len(overlap) / len(requested_grams)
        score = coverage
        if requested_normalized and requested_normalized in combined_normalized:
            score += 2.0
        if document.doc_id in content_matches:
            score += 1.0
        if context_grams:
            score += 4.0 * len(context_grams & combined_grams) / len(context_grams)
        scored.append((score, document.doc_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return []
    threshold = max(0.35, scored[0][0] * 0.6)
    selected = [doc_id for score, doc_id in scored if score >= threshold][:limit]
    return selected or [doc_id for _, doc_id in scored[:limit]]


def _round_robin_documents(
    hits: list[SearchHit],
    *,
    limit: int,
) -> list[SearchHit]:
    buckets: dict[str, list[SearchHit]] = {}
    for hit in hits:
        buckets.setdefault(hit.doc_id, []).append(hit)
    results: list[SearchHit] = []
    while len(results) < limit:
        added = False
        for bucket in buckets.values():
            if bucket and len(results) < limit:
                results.append(bucket.pop(0))
                added = True
        if not added:
            break
    return results


def search_chunks(
    db: Session,
    question: str,
    *,
    top_k: int = 5,
    candidate_limit: int = 100_000,
) -> list[SearchHit]:
    title_match = BOOK_TITLE_PATTERN.search(question)
    requested_title = title_match.group(1).strip() if title_match else None
    requested_extensions = _requested_extensions(question)

    statement = (
        select(KnowledgeChunk, Document)
        .join(Document, Document.doc_id == KnowledgeChunk.doc_id)
        .where(
            Document.is_active.is_(True),
            Document.ingest_status == "indexed",
            Document.duplicate_of_doc_id.is_(None),
        )
    )
    if requested_extensions:
        statement = statement.where(Document.extension.in_(requested_extensions))
    if requested_title:
        candidate_doc_ids = _candidate_document_ids(
            db,
            requested_title,
            question=question,
            extensions=requested_extensions,
        )
        if candidate_doc_ids:
            statement = statement.where(KnowledgeChunk.doc_id.in_(candidate_doc_ids))
    statement = statement.limit(candidate_limit)

    scored: list[SearchHit] = []
    for chunk, document in db.execute(statement).all():
        score = _score(
            question,
            title=f"{document.source_title} {document.original_filename}",
            search_text=chunk.search_text,
            content=chunk.content,
            requested_title=requested_title,
        )
        if score <= 0:
            continue
        try:
            metadata = json.loads(chunk.metadata_json)
        except json.JSONDecodeError:
            metadata = {}
        row_number = metadata.get("row")
        if isinstance(row_number, int) and row_number > 0:
            score += 0.5 / (1.0 + row_number / 10.0)
        scored.append(
            SearchHit(
                chunk_id=chunk.chunk_id,
                doc_id=document.doc_id,
                title=document.source_title,
                source_file=document.original_filename,
                locator=chunk.locator,
                chunk_type=chunk.chunk_type,
                content=chunk.content,
                score=score,
                metadata=metadata,
            )
        )

    scored.sort(key=lambda item: (-item.score, item.doc_id, item.locator))
    if not scored:
        return []

    best = scored[0].score
    threshold = max(0.35, best * 0.35)
    eligible = [item for item in scored if item.score >= threshold]
    if requested_title and "候选表述：" in question:
        return _round_robin_documents(eligible, limit=max(1, top_k))
    return eligible[: max(1, top_k)]


def reciprocal_rank(hits: list[SearchHit], expected_doc_id: str) -> float:
    for rank, hit in enumerate(hits, start=1):
        if hit.doc_id == expected_doc_id:
            return 1.0 / rank
    return 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan
