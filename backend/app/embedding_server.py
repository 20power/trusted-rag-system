from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str = "float"


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingItem]
    model: str
    usage: dict[str, int]


@dataclass(slots=True)
class RuntimeConfig:
    model_name: str
    device: str | None
    batch_size: int
    max_sequence_length: int

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        device = os.getenv("EMBEDDING_SERVER_DEVICE", "").strip() or None
        return cls(
            model_name=os.getenv("EMBEDDING_SERVER_MODEL", "BAAI/bge-m3").strip(),
            device=device,
            batch_size=max(1, int(os.getenv("EMBEDDING_SERVER_BATCH_SIZE", "32"))),
            max_sequence_length=max(
                128,
                int(os.getenv("EMBEDDING_SERVER_MAX_SEQUENCE_LENGTH", "1024")),
            ),
        )


class SentenceTransformerRuntime:
    def __init__(self, config: RuntimeConfig) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "未安装模型运行依赖，请执行：pip install -e '.[model-runtime]'"
            ) from exc

        logger.info(
            "正在加载 Embedding 模型 model=%s device=%s",
            config.model_name,
            config.device or "auto",
        )
        kwargs: dict[str, Any] = {}
        if config.device:
            kwargs["device"] = config.device
        self.model = SentenceTransformer(config.model_name, **kwargs)
        self.model.max_seq_length = config.max_sequence_length
        self.config = config
        dimension_getter = getattr(self.model, "get_embedding_dimension", None)
        if dimension_getter is None:
            dimension_getter = self.model.get_sentence_embedding_dimension
        self.dimension = int(dimension_getter())
        logger.info(
            "Embedding 模型加载完成 model=%s dimension=%s max_seq_length=%s",
            config.model_name,
            self.dimension,
            self.model.max_seq_length,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=self.config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()


runtime: SentenceTransformerRuntime | None = None
runtime_config = RuntimeConfig.from_environment()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global runtime
    runtime = SentenceTransformerRuntime(runtime_config)
    yield
    runtime = None


app = FastAPI(
    title="Trusted RAG Embedding Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(status_code=503, detail="model is loading")
    return {
        "status": "ok",
        "model": runtime_config.model_name,
        "dimension": runtime.dimension,
        "max_sequence_length": runtime.model.max_seq_length,
    }


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    if runtime is None:
        raise HTTPException(status_code=503, detail="model is loading")
    if request.encoding_format != "float":
        raise HTTPException(
            status_code=400,
            detail="当前离线服务仅支持 encoding_format=float",
        )
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts:
        raise HTTPException(status_code=400, detail="input 不能为空")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise HTTPException(status_code=400, detail="input 必须为非空字符串")

    vectors = runtime.embed(texts)
    return EmbeddingResponse(
        data=[
            EmbeddingItem(index=index, embedding=vector)
            for index, vector in enumerate(vectors)
        ],
        model=runtime_config.model_name,
        usage={"prompt_tokens": 0, "total_tokens": 0},
    )
