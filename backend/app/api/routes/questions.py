import uuid

from fastapi import APIRouter

from app.api.dependencies import AppSettings, DbSession
from app.schemas.system import QuestionRequest, QuestionResponse
from app.services.answering import build_answer
from app.services.hybrid_retrieval import retrieve_chunks

router = APIRouter()


@router.post("/ask", response_model=QuestionResponse)
def ask_question(
    request: QuestionRequest,
    settings: AppSettings,
    db: DbSession,
) -> QuestionResponse:
    trace_id = uuid.uuid4().hex
    retrieval = retrieve_chunks(
        db,
        request.question,
        settings=settings,
        top_k=request.top_k,
    )
    hits = retrieval.hits
    evidence = [hit.to_evidence() for hit in hits]
    result = build_answer(
        question=request.question,
        hits=hits,
        settings=settings,
    )
    return QuestionResponse(
        status=result.status,
        answer=result.answer,
        answer_mode=result.answer_mode,
        retrieval_mode=retrieval.mode,
        evidence=evidence,
        citations=result.citations,
        warnings=[*retrieval.warnings, *result.warnings],
        trace_id=trace_id,
    )
