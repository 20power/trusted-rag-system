from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_TEXT_CHARS = 900
TEXT_OVERLAP_CHARS = 120


@dataclass(slots=True)
class ChunkDraft:
    chunk_id: str
    doc_id: str
    chunk_type: str
    locator: str
    content: str
    search_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _chunk_id(doc_id: str, locator: str, content: str) -> str:
    digest = hashlib.sha256(f"{doc_id}\0{locator}\0{content}".encode()).hexdigest()[:16]
    return f"{doc_id}:{digest}"


def _split_long_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> list[str]:
    text = _clean_text(text)
    if len(text) <= max_chars:
        return [text] if text else []

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(
                text.rfind("。", start, end),
                text.rfind("；", start, end),
                text.rfind("\n", start, end),
            )
            if boundary > start + max_chars // 2:
                end = boundary + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - TEXT_OVERLAP_CHARS, start + 1)
    return [piece for piece in pieces if piece]


def _make_chunk(
    *,
    doc_id: str,
    title: str,
    chunk_type: str,
    locator: str,
    content: str,
    metadata: dict[str, Any],
    context: str = "",
) -> ChunkDraft:
    clean_content = _clean_text(content)
    search_text = _clean_text(" ".join((title, context, clean_content)))
    return ChunkDraft(
        chunk_id=_chunk_id(doc_id, locator, clean_content),
        doc_id=doc_id,
        chunk_type=chunk_type,
        locator=locator,
        content=clean_content,
        search_text=search_text,
        metadata=metadata,
    )


def _text_chunks(
    *,
    doc_id: str,
    title: str,
    text_blocks: list[dict[str, Any]],
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for block in text_blocks:
        base_locator = str(block.get("locator") or "text")
        block_type = str(block.get("block_type") or "paragraph")
        metadata = dict(block.get("metadata") or {})
        section_path = [
            _clean_text(item)
            for item in metadata.get("section_path") or []
            if _clean_text(item)
        ]
        context_parts = section_path[:]
        article_no = _clean_text(metadata.get("article_no"))
        if article_no and article_no not in context_parts:
            context_parts.append(article_no)
        context = " > ".join(context_parts)
        for part_index, part in enumerate(_split_long_text(str(block.get("text") or "")), start=1):
            locator = base_locator
            if part_index > 1:
                locator = f"{base_locator}:part:{part_index}"
            chunks.append(
                _make_chunk(
                    doc_id=doc_id,
                    title=title,
                    chunk_type=block_type,
                    locator=locator,
                    content=part,
                    metadata={**metadata, "part": part_index},
                    context=context,
                )
            )
    return chunks


def _word_table_chunks(
    *,
    doc_id: str,
    title: str,
    tables: list[dict[str, Any]],
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for table in tables:
        table_index = int(table.get("table_index") or 0)
        rows = list(table.get("rows") or [])
        header_values: list[str] = []
        if rows:
            header_values = [_clean_text(cell.get("text")) for cell in rows[0]]
        for row_index, cells in enumerate(rows, start=1):
            values = [_clean_text(cell.get("text")) for cell in cells]
            if not any(values):
                continue
            parts = []
            for column_index, value in enumerate(values, start=1):
                if not value:
                    continue
                header = (
                    header_values[column_index - 1]
                    if column_index - 1 < len(header_values)
                    else ""
                )
                label = header if header and row_index > 1 else f"第{column_index}列"
                parts.append(f"{label}={value}")
            locator = f"table:{table_index}:row:{row_index}"
            chunks.append(
                _make_chunk(
                    doc_id=doc_id,
                    title=title,
                    chunk_type="table_row",
                    locator=locator,
                    content="；".join(parts),
                    context=f"表格{table_index}",
                    metadata={
                        "table_index": table_index,
                        "row": row_index,
                        "cells": cells,
                    },
                )
            )
    return chunks


def _spreadsheet_chunks(
    *,
    doc_id: str,
    title: str,
    workbook: dict[str, Any],
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for sheet in workbook.get("sheets") or []:
        sheet_name = _clean_text(sheet.get("name"))
        cells = list(sheet.get("cells") or [])
        rows: dict[int, list[dict[str, Any]]] = {}
        for cell in cells:
            value = cell.get("value")
            if value is None or _clean_text(value) == "":
                continue
            rows.setdefault(int(cell["row"]), []).append(cell)

        section_rows: dict[int, str] = {}
        for row_number, row_cells in rows.items():
            values = [_clean_text(cell.get("value")) for cell in row_cells]
            text_values = [value for value in values if value]
            if (
                len(text_values) == 1
                and re.match(r"^(?:\d+[.、]\s*|其中[：:]?)", text_values[0])
            ):
                section_rows[row_number] = text_values[0]

        header_fragments: list[str] = []
        header_cells: list[dict[str, Any]] = []
        first_row = min(rows) if rows else 1
        for row_number in sorted(rows):
            if row_number > first_row + 4:
                break
            if row_number in section_rows:
                continue
            for cell in rows[row_number]:
                value = cell.get("value")
                if isinstance(value, str) and _clean_text(value):
                    header_fragments.append(f"{cell['address']}={_clean_text(value)}")
                    header_cells.append(
                        {
                            "address": cell["address"],
                            "row": cell["row"],
                            "column": cell["column"],
                            "value": _clean_text(value),
                        }
                    )
        header_context = "；".join(header_fragments[:40])

        current_section = ""
        for row_number in sorted(rows):
            if row_number in section_rows:
                current_section = section_rows[row_number]
            row_cells = sorted(rows[row_number], key=lambda item: int(item["column"]))
            row_text = "；".join(
                f"{cell['address']}={_clean_text(cell.get('value'))}" for cell in row_cells
            )
            if current_section and row_number not in section_rows:
                row_text = f"分组={current_section}；{row_text}"
            addresses = [str(cell["address"]) for cell in row_cells]
            locator = f"sheet:{sheet_name}!{addresses[0]}:{addresses[-1]}"
            chunks.append(
                _make_chunk(
                    doc_id=doc_id,
                    title=title,
                    chunk_type="sheet_row",
                    locator=locator,
                    content=row_text,
                    context=f"工作表={sheet_name}；表头={header_context}",
                    metadata={
                        "sheet": sheet_name,
                        "row": row_number,
                        "section": current_section or None,
                        "header_cells": header_cells,
                        "addresses": addresses,
                        "cells": row_cells,
                    },
                )
            )
    return chunks


def build_chunks(
    *,
    doc_id: str,
    title: str,
    parsed_payload: dict[str, Any],
) -> list[ChunkDraft]:
    content = dict(parsed_payload.get("content") or {})
    chunks = _text_chunks(
        doc_id=doc_id,
        title=title,
        text_blocks=list(content.get("text_blocks") or []),
    )
    chunks.extend(
        _word_table_chunks(
            doc_id=doc_id,
            title=title,
            tables=list(content.get("tables") or []),
        )
    )
    workbook = content.get("workbook")
    if isinstance(workbook, dict):
        chunks.extend(
            _spreadsheet_chunks(
                doc_id=doc_id,
                title=title,
                workbook=workbook,
            )
        )
    return chunks


def metadata_as_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
