from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from app.services.parsers import converter
from app.services.parsers.xlsx_parser import parse_xlsx


def test_xlsx_parser_ignores_invalid_row_only_auto_filter(tmp_path: Path) -> None:
    source = tmp_path / "invalid-filter.xlsx"
    original = tmp_path / "original.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet["A1"] = "指标"
    worksheet["B1"] = "数值"
    worksheet["A2"] = "资本充足率"
    worksheet["B2"] = 12
    worksheet.auto_filter.ref = "A1:B2"
    workbook.save(original)

    with ZipFile(original, "r") as input_archive, ZipFile(
        source,
        "w",
        compression=ZIP_DEFLATED,
    ) as output_archive:
        for info in input_archive.infolist():
            payload = input_archive.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(b'ref="A1:B2"', b'ref="1:2"')
            output_archive.writestr(info, payload)

    parsed = parse_xlsx(source, max_cells=100)

    assert parsed.workbook is not None
    assert parsed.workbook["non_empty_cells"] == 4
    assert parsed.warnings == ["已忽略不符合OOXML单元格范围规范的自动筛选元数据"]


def test_legacy_converter_uses_short_temporary_filename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / ("很长的监管文件名" * 5 + ".doc")
    source.write_bytes(b"legacy-doc")
    seen_source: list[Path] = []

    def fake_run(command, **_kwargs):
        temporary_source = Path(command[-1])
        seen_source.append(temporary_source)
        (Path(command[-2]) / "source.docx").write_bytes(b"converted")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(converter, "find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(converter.subprocess, "run", fake_run)

    output = converter.convert_legacy_office(
        source,
        output_dir=tmp_path / "converted",
        doc_id="NFRA-426-test",
        timeout_seconds=30,
    )

    assert seen_source[0].name == "source.doc"
    assert output.name == "NFRA-426-test.docx"
    assert output.read_bytes() == b"converted"
