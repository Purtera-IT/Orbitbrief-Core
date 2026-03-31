from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook

from orbitbrief_core.runtime_spine.file_utils import synthetic_minimal_pdf


def write_docx(path: Path, text: str) -> None:
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def write_xlsx(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sites"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def write_pdf(path: Path, text: str) -> None:
    path.write_bytes(synthetic_minimal_pdf(text))
