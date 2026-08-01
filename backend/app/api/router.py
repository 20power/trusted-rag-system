from fastapi import APIRouter

from app.api.routes import documents, evaluation, health, ingestion, questions, system

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
api_router.include_router(questions.router, prefix="/questions", tags=["questions"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
