from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings


class EmbeddingClientError(RuntimeError):
    pass


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.settings.embedding_is_configured:
            raise EmbeddingClientError("Embedding Provider 尚未配置")

        headers = {"Content-Type": "application/json"}
        if self.settings.embedding_api_key:
            headers["Authorization"] = f"Bearer {self.settings.embedding_api_key}"
        endpoint = f"{self.settings.embedding_base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self.settings.embedding_model,
            "input": texts,
        }
        try:
            with httpx.Client(
                timeout=self.settings.embedding_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                body: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingClientError(f"Embedding 请求失败：{exc}") from exc

        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingClientError("Embedding 返回数量与输入不一致")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in ordered:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or not vector:
                raise EmbeddingClientError("Embedding 响应缺少向量")
            if not all(isinstance(value, (int, float)) for value in vector):
                raise EmbeddingClientError("Embedding 向量包含非数值元素")
            vectors.append([float(value) for value in vector])
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise EmbeddingClientError("Embedding 向量维度不一致")
        return vectors


EmbeddingFactory = Callable[[Settings], OpenAICompatibleEmbeddingClient]
