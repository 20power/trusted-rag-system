from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings

POINT_NAMESPACE = uuid.UUID("3ee42837-0119-4b50-b195-0e249e790f41")


class VectorStoreError(RuntimeError):
    pass


@dataclass(slots=True)
class VectorMatch:
    chunk_id: str
    score: float


class QdrantVectorStore:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = settings.qdrant_url.rstrip("/")
        self.collection = settings.qdrant_collection
        self.timeout = settings.embedding_timeout_seconds
        self.transport = transport

    def _request(self, method: str, path: str, *, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VectorStoreError(f"Qdrant 请求失败：{exc}") from exc

    def ensure_collection(self, vector_size: int) -> None:
        path = f"/collections/{self.collection}"
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(f"{self.base_url}{path}")
                if response.status_code == 200:
                    body = response.json()
                    configured_size = (
                        body.get("result", {})
                        .get("config", {})
                        .get("params", {})
                        .get("vectors", {})
                        .get("size")
                    )
                    if configured_size not in (None, vector_size):
                        raise VectorStoreError(
                            f"Qdrant 集合向量维度为 {configured_size}，当前模型为 {vector_size}"
                        )
                    return
                if response.status_code != 404:
                    response.raise_for_status()
        except VectorStoreError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise VectorStoreError(f"Qdrant 集合检查失败：{exc}") from exc

        self._request(
            "PUT",
            path,
            payload={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )

    def upsert(
        self,
        records: list[tuple[str, list[float], dict[str, Any]]],
    ) -> None:
        if not records:
            return
        points = [
            {
                "id": str(uuid.uuid5(POINT_NAMESPACE, chunk_id)),
                "vector": vector,
                "payload": {"chunk_id": chunk_id, **payload},
            }
            for chunk_id, vector, payload in records
        ]
        self._request(
            "PUT",
            f"/collections/{self.collection}/points?wait=true",
            payload={"points": points},
        )

    def search(
        self,
        vector: list[float],
        *,
        limit: int,
        doc_ids: list[str] | None = None,
    ) -> list[VectorMatch]:
        payload: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": ["chunk_id"],
            "with_vector": False,
        }
        if doc_ids:
            payload["filter"] = {
                "must": [{"key": "doc_id", "match": {"any": doc_ids}}]
            }
        body = self._request(
            "POST",
            f"/collections/{self.collection}/points/search",
            payload=payload,
        )
        result = body.get("result")
        if not isinstance(result, list):
            raise VectorStoreError("Qdrant 检索响应缺少 result")
        matches: list[VectorMatch] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            chunk_id = payload.get("chunk_id") if isinstance(payload, dict) else None
            score = item.get("score")
            if isinstance(chunk_id, str) and isinstance(score, (int, float)):
                matches.append(VectorMatch(chunk_id=chunk_id, score=float(score)))
        return matches
