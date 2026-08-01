from pydantic import BaseModel


class RetrievalBaseline(BaseModel):
    source_type: str
    available: bool
    case_count: int = 0
    top_k: int = 5
    document_recall_at_k: float = 0.0
    evidence_recall_at_k: float = 0.0
    evidence_mrr: float = 0.0
    generated_at: str | None = None


class EvaluationSummary(BaseModel):
    baselines: list[RetrievalBaseline]
