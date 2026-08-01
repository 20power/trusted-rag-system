from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, IngestionRun

SUPPORTED_EXTENSIONS = {".doc", ".docx", ".pdf", ".xls", ".xlsx"}
SOURCE_FILENAME_MAP = "source-filename-map.json"
MIME_OVERRIDES = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ManifestEntry:
    doc_id: str
    source_title: str
    original_filename: str
    relative_path: str
    source_path: str
    extension: str
    mime_type: str
    file_signature: str
    size_bytes: int
    sha256: str
    sequence_no: int | None
    year_hint: int | None
    duplicate_of_doc_id: str | None
    version_status: str = "unknown"


@dataclass(slots=True)
class ScanResult:
    run_id: str
    discovered_files: int
    new_files: int
    updated_files: int
    duplicate_files: int
    failed_files: int
    manifest_path: str
    extension_counts: dict[str, int]
    total_bytes: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_signature(path: Path) -> str:
    with path.open("rb") as handle:
        head = handle.read(8)
    if head.startswith(b"PK\x03\x04"):
        return "zip/ooxml"
    if head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "ole-compound"
    if head.startswith(b"%PDF"):
        return "pdf"
    return head.hex() or "empty"


def parse_sequence(filename: str) -> int | None:
    match = re.match(r"^(\d{3})_", filename)
    return int(match.group(1)) if match else None


def parse_year(filename: str) -> int | None:
    match = re.search(r"(20\d{2})年", filename)
    return int(match.group(1)) if match else None


def normalize_title(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d{3}_", "", stem)
    page_title = stem.split("_", maxsplit=1)[0]
    return page_title.strip() or stem


def build_doc_id(filename: str, digest: str) -> str:
    sequence = parse_sequence(filename)
    if sequence is not None:
        return f"NFRA-{sequence:03d}-{digest[:10]}"
    return f"DOC-{digest[:16]}"


def build_manifest_entries(source_dir: Path) -> tuple[list[ManifestEntry], list[str]]:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"数据目录不存在或不可访问：{source_dir}")

    filename_map: dict[str, str] = {}
    filename_map_path = source_dir / SOURCE_FILENAME_MAP
    if filename_map_path.is_file():
        try:
            payload = json.loads(filename_map_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                filename_map = {
                    str(key).replace("\\", "/"): str(value)
                    for key, value in payload.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"源文件名映射无效：{filename_map_path}: {exc}") from exc

    files = sorted(
        (
            path
            for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda item: item.relative_to(source_dir).as_posix(),
    )
    entries: list[ManifestEntry] = []
    errors: list[str] = []
    first_by_hash: dict[str, str] = {}

    for path in files:
        try:
            physical_relative_path = path.relative_to(source_dir).as_posix()
            original_filename = filename_map.get(physical_relative_path, path.name)
            logical_relative_path = (
                Path(physical_relative_path)
                .with_name(original_filename)
                .as_posix()
            )
            digest = sha256_file(path)
            doc_id = build_doc_id(original_filename, digest)
            duplicate_of = first_by_hash.get(digest)
            first_by_hash.setdefault(digest, doc_id)
            extension = path.suffix.lower()
            mime_type = MIME_OVERRIDES.get(
                extension,
                mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
            )
            entries.append(
                ManifestEntry(
                    doc_id=doc_id,
                    source_title=normalize_title(original_filename),
                    original_filename=original_filename,
                    relative_path=logical_relative_path,
                    source_path=str(path.resolve()),
                    extension=extension,
                    mime_type=mime_type,
                    file_signature=detect_signature(path),
                    size_bytes=path.stat().st_size,
                    sha256=digest,
                    sequence_no=parse_sequence(original_filename),
                    year_hint=parse_year(original_filename),
                    duplicate_of_doc_id=duplicate_of,
                )
            )
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return entries, errors


def _write_manifest(settings: Settings, entries: list[ManifestEntry], errors: list[str]) -> Path:
    settings.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.manifest_dir / "document_manifest.jsonl"
    temporary_path = manifest_path.with_suffix(".jsonl.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True) + "\n")
    temporary_path.replace(manifest_path)

    summary = {
        "schema_version": "1.0",
        "generated_at": utc_iso(),
        "source_dir": str(settings.source_data_dir.resolve()),
        "file_count": len(entries),
        "total_bytes": sum(entry.size_bytes for entry in entries),
        "extension_counts": dict(Counter(entry.extension for entry in entries)),
        "duplicate_files": sum(entry.duplicate_of_doc_id is not None for entry in entries),
        "errors": errors,
        "source_metadata_status": "local_manifest_only; source URLs were not supplied",
    }
    summary_path = settings.manifest_dir / "manifest_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def scan_source_directory(db: Session, settings: Settings) -> ScanResult:
    settings.ensure_runtime_dirs()
    run_id = uuid.uuid4().hex
    run = IngestionRun(run_id=run_id, status="running", source_dir=str(settings.source_data_dir))
    db.add(run)
    db.commit()

    try:
        entries, errors = build_manifest_entries(settings.source_data_dir)
        manifest_path = _write_manifest(settings, entries, errors)
        current_paths = {entry.relative_path for entry in entries}

        existing = {
            document.relative_path: document
            for document in db.scalars(select(Document)).all()
        }
        for document in existing.values():
            if document.relative_path not in current_paths:
                document.is_active = False

        new_files = 0
        updated_files = 0
        for entry in entries:
            document = existing.get(entry.relative_path)
            payload = asdict(entry)
            if document is None:
                document = Document(**payload, ingest_status="discovered", is_active=True)
                db.add(document)
                new_files += 1
                continue

            content_changed = document.sha256 != entry.sha256
            for key, value in payload.items():
                setattr(document, key, value)
            document.is_active = True
            if content_changed:
                document.ingest_status = "discovered"
                document.parsed_artifact_path = None
                document.error_code = None
                document.error_message = None
            updated_files += 1

        run.status = "completed"
        run.discovered_files = len(entries)
        run.new_files = new_files
        run.updated_files = updated_files
        run.duplicate_files = sum(entry.duplicate_of_doc_id is not None for entry in entries)
        run.failed_files = len(errors)
        run.manifest_path = str(manifest_path)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

        return ScanResult(
            run_id=run_id,
            discovered_files=len(entries),
            new_files=new_files,
            updated_files=updated_files,
            duplicate_files=run.duplicate_files,
            failed_files=len(errors),
            manifest_path=str(manifest_path),
            extension_counts=dict(Counter(entry.extension for entry in entries)),
            total_bytes=sum(entry.size_bytes for entry in entries),
        )
    except Exception as exc:
        db.rollback()
        persisted_run = db.scalar(select(IngestionRun).where(IngestionRun.run_id == run_id))
        if persisted_run is not None:
            persisted_run.status = "failed"
            persisted_run.error_message = str(exc)
            persisted_run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
