from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db.base import Base  # noqa: E402


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_source_dir(tmp_path: Path) -> Path:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "001_2026年测试统计表_测试统计表.xls").write_bytes(
        bytes.fromhex("D0CF11E0A1B11AE1") + b"test-xls"
    )
    (source / "002_测试制度_测试制度.pdf").write_bytes(b"%PDF-1.4\ntest")
    (source / "003_测试制度副本_测试制度副本.pdf").write_bytes(b"%PDF-1.4\ntest")
    return source
