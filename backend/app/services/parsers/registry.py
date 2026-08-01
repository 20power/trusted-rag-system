from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.db.models import Document
from app.services.parsers.common import write_parsed_artifact
from app.services.parsers.converter import convert_legacy_office
from app.services.parsers.docx_parser import parse_docx
from app.services.parsers.pdf_parser import parse_pdf
from app.services.parsers.xlsx_parser import parse_xlsx

PARSER_VERSION = "0.2.0"


def parse_document(document: Document, settings: Settings) -> Path:
    source = Path(document.source_path).resolve()
    source_root = settings.source_data_dir.resolve()
    if source_root not in source.parents and source != source_root:
        raise ValueError("拒绝解析数据目录之外的文件")
    if not source.is_file():
        raise FileNotFoundError(f"源文件不存在：{source}")

    parse_source = source
    extension = document.extension.lower()
    if extension in {".doc", ".xls"}:
        parse_source = convert_legacy_office(
            source,
            output_dir=settings.conversion_dir,
            doc_id=document.doc_id,
            timeout_seconds=settings.parser_timeout_seconds,
        )
        extension = parse_source.suffix.lower()

    if extension == ".docx":
        content = parse_docx(parse_source)
    elif extension == ".pdf":
        content = parse_pdf(parse_source)
    elif extension == ".xlsx":
        content = parse_xlsx(parse_source, max_cells=settings.parser_max_cells)
    else:
        raise ValueError(f"暂不支持的格式：{extension}")

    output_path = settings.parsed_dir / f"{document.doc_id}.json"
    write_parsed_artifact(
        output_path,
        doc_id=document.doc_id,
        source_path=source,
        content=content,
    )
    return output_path
