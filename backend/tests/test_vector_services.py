from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.db.models import Document, KnowledgeChunk
from app.services.embedding_client import (
    EmbeddingClientError,
    OpenAICompatibleEmbeddingClient,
)
from app.services.hybrid_retrieval import _uses_lexical_policy, retrieve_chunks
from app.services.vector_indexing import index_chunk_vectors
from app.services.vector_store import QdrantVectorStore, VectorMatch


def _settings(**overrides: object) -> Settings:
    return Settings(
        embedding_provider="local",
        embedding_base_url="http://embedding.test/v1",
        embedding_api_key="secret",
        embedding_model="test-embedding",
        qdrant_url="http://qdrant.test",
        embedding_batch_size=2,
        **overrides,
    )


def _seed_chunks(db) -> None:
    document = Document(
        doc_id="NFRA-VECTOR-001",
        source_title="测试监管办法",
        original_filename="测试监管办法.docx",
        relative_path="测试监管办法.docx",
        source_path="C:/raw/测试监管办法.docx",
        extension=".docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_signature="zip-ooxml",
        size_bytes=100,
        sha256="b" * 64,
        ingest_status="indexed",
    )
    db.add(document)
    db.add_all(
        [
            KnowledgeChunk(
                chunk_id=f"chunk-{index}",
                doc_id=document.doc_id,
                chunk_type="paragraph",
                locator=f"paragraph:{index}",
                content=content,
                search_text=f"测试监管办法 {content}",
                metadata_json="{}",
                character_count=len(content),
            )
            for index, content in enumerate(
                ["交易账簿包括短期持有头寸", "银行账簿包括其他头寸", "第三条测试内容"],
                start=1,
            )
        ]
    )
    db.commit()


def test_embedding_client_uses_openai_compatible_protocol() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    vectors = client.embed(["第一段", "第二段"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"] == {
        "model": "test-embedding",
        "input": ["第一段", "第二段"],
    }


def test_qdrant_store_creates_collection_and_returns_chunk_ids() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(404, json={"status": "not found"})
        if request.url.path.endswith("/points/search"):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"score": 0.91, "payload": {"chunk_id": "chunk-1"}}
                    ]
                },
            )
        return httpx.Response(200, json={"result": True})

    store = QdrantVectorStore(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    store.ensure_collection(2)
    store.upsert([("chunk-1", [0.1, 0.2], {"doc_id": "doc-1"})])
    matches = store.search([0.1, 0.2], limit=5)

    assert matches == [VectorMatch(chunk_id="chunk-1", score=0.91)]
    assert ("PUT", "/collections/regulatory_knowledge") in requests
    assert (
        "PUT",
        "/collections/regulatory_knowledge/points",
    ) in requests


def test_hybrid_retrieval_falls_back_when_embedding_service_fails(db) -> None:
    _seed_chunks(db)

    class FailingEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingClientError("service unavailable")

    result = retrieve_chunks(
        db,
        "交易账簿包括什么",
        settings=_settings(),
        top_k=2,
        embedding_client=FailingEmbedder(),  # type: ignore[arg-type]
    )

    assert result.mode == "lexical_fallback"
    assert result.hits[0].chunk_id == "chunk-1"
    assert result.warnings


def test_hybrid_fusion_preserves_exact_oriented_formats() -> None:
    assert _uses_lexical_policy("根据 PDF 附件回答")
    assert _uses_lexical_policy("根据 Excel 附件取数")
    assert not _uses_lexical_policy("根据 Word 附件回答")


def test_vector_indexing_is_batched_and_idempotent_ready(db) -> None:
    _seed_chunks(db)

    class FakeEmbedder:
        calls: list[list[str]] = []

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(texts)
            return [[float(index), 1.0] for index, _ in enumerate(texts, start=1)]

    class FakeStore:
        vector_size = 0
        records: list[tuple[str, list[float], dict[str, object]]] = []

        def ensure_collection(self, vector_size: int) -> None:
            self.vector_size = vector_size

        def upsert(
            self,
            records: list[tuple[str, list[float], dict[str, object]]],
        ) -> None:
            self.records.extend(records)

    embedder = FakeEmbedder()
    store = FakeStore()
    report = index_chunk_vectors(
        db,
        _settings(),
        embedding_client=embedder,  # type: ignore[arg-type]
        vector_store=store,  # type: ignore[arg-type]
    )

    assert report.indexed_chunks == 3
    assert report.vector_size == 2
    assert report.batch_count == 2
    assert [record[0] for record in store.records] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
    ]
