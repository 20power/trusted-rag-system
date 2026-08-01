from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "可信监管 RAG 系统"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./data/runtime/trusted_rag.db"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "regulatory_knowledge"

    source_data_dir: Path = Path("../nfra_page_attachments_500")
    qa_workbook_path: Path = Path("../QA数据.xlsx")
    derived_data_dir: Path = Path("./data/derived")

    llm_provider: Literal["local", "cloud", "disabled"] = "disabled"
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = Field(default=60, ge=5, le=600)
    llm_max_tokens: int = Field(default=800, ge=64, le=8192)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)

    embedding_provider: Literal["local", "cloud", "disabled"] = "disabled"
    embedding_base_url: str = "http://localhost:8002/v1"
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_timeout_seconds: int = Field(default=60, ge=5, le=600)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    hybrid_candidate_count: int = Field(default=40, ge=5, le=500)

    parser_max_cells: int = Field(default=2_000_000, ge=1_000)
    parser_timeout_seconds: int = Field(default=300, ge=10, le=3600)

    @field_validator("source_data_dir", "qa_workbook_path", "derived_data_dir", mode="before")
    @classmethod
    def expand_paths(cls, value: object) -> Path:
        return Path(str(value)).expanduser()

    @model_validator(mode="after")
    def resolve_project_paths(self) -> Settings:
        for attribute in ("source_data_dir", "qa_workbook_path", "derived_data_dir"):
            value = getattr(self, attribute)
            if not value.is_absolute():
                setattr(self, attribute, (PROJECT_ROOT / value).resolve())

        sqlite_prefix = "sqlite:///"
        if (
            self.database_url.startswith(f"{sqlite_prefix}.")
            and self.database_url != "sqlite:///:memory:"
        ):
            relative_path = Path(self.database_url.removeprefix(sqlite_prefix))
            absolute_path = (PROJECT_ROOT / relative_path).resolve()
            self.database_url = f"{sqlite_prefix}{absolute_path.as_posix()}"
        return self

    @property
    def manifest_dir(self) -> Path:
        return self.derived_data_dir / "manifest"

    @property
    def parsed_dir(self) -> Path:
        return self.derived_data_dir / "parsed"

    @property
    def conversion_dir(self) -> Path:
        return self.derived_data_dir / "converted"

    @property
    def evaluation_dir(self) -> Path:
        return self.derived_data_dir / "evaluation"

    @property
    def llm_is_configured(self) -> bool:
        return self.llm_provider != "disabled" and bool(
            self.llm_base_url.strip() and self.llm_model.strip()
        )

    @property
    def embedding_is_configured(self) -> bool:
        return self.embedding_provider != "disabled" and bool(
            self.embedding_base_url.strip() and self.embedding_model.strip()
        )

    def ensure_runtime_dirs(self) -> None:
        self.derived_data_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)
        self.conversion_dir.mkdir(parents=True, exist_ok=True)
        self.evaluation_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            database_path = self.database_url.removeprefix("sqlite:///")
            if database_path and database_path != ":memory:":
                Path(database_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
