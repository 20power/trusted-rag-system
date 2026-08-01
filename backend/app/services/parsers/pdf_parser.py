from pathlib import Path

from pypdf import PdfReader

from app.services.parsers.common import ParsedContent, TextBlock

PARSER_VERSION = "0.1.0"


def parse_pdf(path: Path) -> ParsedContent:
    reader = PdfReader(path)
    blocks: list[TextBlock] = []
    warnings: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(
                TextBlock(
                    locator=f"page:{page_number}",
                    text=text,
                    block_type="page",
                    metadata={"page_number": page_number},
                )
            )
        else:
            warnings.append(f"第 {page_number} 页没有可提取文本，可能需要 OCR")
    return ParsedContent(
        parser="pypdf",
        parser_version=PARSER_VERSION,
        source_format="pdf",
        text_blocks=blocks,
        warnings=warnings,
    )
