from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.dependencies import AppSettings, DbSession
from app.schemas.system import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    db: DbSession,
    settings: AppSettings,
) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.app_env,
        database="ok",
    )
