from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Document, KnowledgeChunk
from app.services.chunking import build_chunks, metadata_as_json


def index_document(document: Document, db: Session) -> int:
    if not document.parsed_artifact_path:
        raise ValueError("文档尚未生成解析产物")

    artifact_path = Path(document.parsed_artifact_path)
    if not artifact_path.is_file():
        raise FileNotFoundError(f"解析产物不存在：{artifact_path}")

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    chunks = build_chunks(
        doc_id=document.doc_id,
        title=document.source_title,
        parsed_payload=payload,
    )
    if not chunks:
        raise ValueError("解析产物中没有可索引内容")

    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == document.doc_id))
    db.add_all(
        [
            KnowledgeChunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                chunk_type=chunk.chunk_type,
                locator=chunk.locator,
                content=chunk.content,
                search_text=chunk.search_text,
                metadata_json=metadata_as_json(chunk.metadata),
                character_count=len(chunk.content),
            )
            for chunk in chunks
        ]
    )
    document.ingest_status = "indexed"
    db.commit()
    return len(chunks)
