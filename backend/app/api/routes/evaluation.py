from __future__ import annotations

import json

from fastapi import APIRouter

from app.api.dependencies import AppSettings
from app.schemas.evaluation import EvaluationSummary, RetrievalBaseline

router = APIRouter()


@router.get("/summary", response_model=EvaluationSummary)
def evaluation_summary(settings: AppSettings) -> EvaluationSummary:
    baselines: list[RetrievalBaseline] = []
    for source_type in ("excel", "word", "pdf"):
        report_path = settings.evaluation_dir / f"retrieval_{source_type}_baseline.json"
        if not report_path.is_file():
            baselines.append(
                RetrievalBaseline(source_type=source_type, available=False)
            )
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        baselines.append(
            RetrievalBaseline(
                source_type=source_type,
                available=True,
                case_count=int(payload.get("case_count", 0)),
                top_k=int(payload.get("top_k", 5)),
                document_recall_at_k=float(payload.get("document_recall_at_k", 0.0)),
                evidence_recall_at_k=float(payload.get("evidence_recall_at_k", 0.0)),
                evidence_mrr=float(payload.get("evidence_mrr", 0.0)),
                generated_at=payload.get("generated_at"),
            )
        )
    return EvaluationSummary(baselines=baselines)
