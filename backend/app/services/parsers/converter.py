from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class ConversionUnavailableError(RuntimeError):
    pass


def find_soffice() -> str | None:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ]
    return next(
        (candidate for candidate in candidates if candidate and Path(candidate).exists()),
        None,
    )


def convert_legacy_office(
    source: Path,
    *,
    output_dir: Path,
    doc_id: str,
    timeout_seconds: int,
) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise ConversionUnavailableError(
            "未找到 LibreOffice/soffice，无法转换旧版 .doc/.xls；Docker 镜像已包含转换组件"
        )
    target_extension = ".docx" if source.suffix.lower() == ".doc" else ".xlsx"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{doc_id}{target_extension}"
    if final_path.exists():
        return final_path

    with tempfile.TemporaryDirectory(prefix="rag-office-convert-") as temporary:
        temporary_path = Path(temporary)
        profile_path = temporary_path / "profile"
        temporary_source = temporary_path / f"source{source.suffix.lower()}"
        shutil.copy2(source, temporary_source)
        converted_path = temporary_path / f"source{target_extension}"
        profile_uri = profile_path.resolve().as_uri()
        command = [
            soffice,
            "--headless",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            target_extension.removeprefix("."),
            "--outdir",
            str(temporary_path),
            str(temporary_source),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0 or not converted_path.exists():
            raise RuntimeError(
                "旧格式转换失败："
                f"exit={result.returncode}; stdout={result.stdout[-1000:]}; "
                f"stderr={result.stderr[-1000:]}"
            )
        shutil.copy2(converted_path, final_path)
    return final_path
