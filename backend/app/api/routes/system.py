from fastapi import APIRouter

from app import __version__
from app.api.dependencies import AppSettings
from app.schemas.system import SystemInfo

router = APIRouter()


@router.get("/info", response_model=SystemInfo)
def system_info(settings: AppSettings) -> SystemInfo:
    return SystemInfo(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        llm_provider=settings.llm_provider,
        llm_configured=settings.llm_is_configured,
        llm_model=settings.llm_model or None,
        llm_base_url=settings.llm_base_url,
        embedding_provider=settings.embedding_provider,
        embedding_configured=settings.embedding_is_configured,
        source_data_dir=str(settings.source_data_dir),
        source_data_available=settings.source_data_dir.is_dir(),
        qa_workbook_available=settings.qa_workbook_path.is_file(),
        qdrant_url=settings.qdrant_url,
    )
