import json
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings
from app.db.models import Document
from app.services.manifest import build_manifest_entries, scan_source_directory


def test_build_manifest_detects_format_year_and_duplicate(sample_source_dir: Path) -> None:
    entries, errors = build_manifest_entries(sample_source_dir)

    assert errors == []
    assert len(entries) == 3
    assert entries[0].extension == ".xls"
    assert entries[0].file_signature == "ole-compound"
    assert entries[0].year_hint == 2026
    assert entries[2].duplicate_of_doc_id == entries[1].doc_id


def test_scan_persists_documents_and_manifest(db, sample_source_dir: Path, tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite:///:memory:",
        source_data_dir=sample_source_dir,
        qa_workbook_path=tmp_path / "qa.xlsx",
        derived_data_dir=tmp_path / "derived",
    )

    result = scan_source_directory(db, settings)

    assert result.discovered_files == 3
    assert result.new_files == 3
    assert result.duplicate_files == 1
    assert Path(result.manifest_path).is_file()
    assert db.scalar(select(func.count()).select_from(Document)) == 3


def test_manifest_uses_logical_name_for_linux_shortened_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    short_name = "427_source.xls"
    original_name = "427_国家金融监督管理总局_货币经纪公司数据服务通知附件.xls"
    (source / short_name).write_bytes(
        bytes.fromhex("D0CF11E0A1B11AE1") + b"mapped-xls"
    )
    (source / "source-filename-map.json").write_text(
        json.dumps({short_name: original_name}, ensure_ascii=False),
        encoding="utf-8",
    )

    entries, errors = build_manifest_entries(source)

    assert errors == []
    assert len(entries) == 1
    assert entries[0].original_filename == original_name
    assert entries[0].relative_path == original_name
    assert entries[0].sequence_no == 427
    assert entries[0].source_title == "国家金融监督管理总局"
    assert Path(entries[0].source_path).name == short_name
