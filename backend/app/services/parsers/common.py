from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TextBlock:
    locator: str
    text: str
    block_type: str = "paragraph"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedContent:
    parser: str
    parser_version: str
    source_format: str
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    workbook: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_parsed_artifact(
    output_path: Path,
    *,
    doc_id: str,
    source_path: Path,
    content: ParsedContent,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "doc_id": doc_id,
        "source_path": str(source_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content": content.to_dict(),
    }
    temp_path = output_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(output_path)
