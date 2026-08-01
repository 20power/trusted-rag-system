from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str


class SystemInfo(BaseModel):
    app_name: str
    version: str
    environment: str
    llm_provider: str
    llm_configured: bool
    llm_model: str | None
    llm_base_url: str
    embedding_provider: str
    embedding_configured: bool
    source_data_dir: str
    source_data_available: bool
    qa_workbook_available: bool
    qdrant_url: str


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)


class QuestionResponse(BaseModel):
    status: str
    answer: str
    answer_mode: str
    retrieval_mode: str
    evidence: list[dict[str, object]]
    citations: list[dict[str, object]]
    warnings: list[str]
    trace_id: str
