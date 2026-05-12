from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile


@dataclass(frozen=True, slots=True)
class NarrativeBlock:
    block_id: str
    block_type: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NarrativeParseResult:
    parser_id: str
    parser_version: str
    metadata: dict[str, str]
    blocks: list[NarrativeBlock]


class TextNarrativeParser:
    parser_id = "text_narrative_parser"
    parser_version = "1.0.0"
    io_version = "1.0.0"

    def _read_text(self, path: Path, modality: str) -> str:
        modality = modality.lower()
        if modality == "docx":
            with ZipFile(path) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<[^>]+>", "", xml)
            return xml
        return path.read_text(encoding="utf-8", errors="ignore")

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> NarrativeParseResult:
        text = self._read_text(path, modality)
        blocks: list[NarrativeBlock] = []
        for idx, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            block_type = "paragraph"
            cleaned = line
            if line.startswith("#"):
                block_type = "heading"
                cleaned = line.lstrip("# ").strip()
            elif line.startswith("-"):
                block_type = "list_item"
                cleaned = line[1:].strip()
            elif re.match(r"^[A-Z][A-Za-z0-9 /_-]{1,60}:$", line):
                block_type = "heading"
                cleaned = line[:-1]
            blocks.append(
                NarrativeBlock(
                    block_id=f"block_{idx:04d}",
                    block_type=block_type,
                    text=cleaned,
                    metadata={"modality": modality.lower(), "role_hint": role_hint or ""},
                )
            )
        return NarrativeParseResult(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            metadata={"io_version": self.io_version, "modality": modality.lower()},
            blocks=blocks,
        )


__all__ = ["NarrativeBlock", "NarrativeParseResult", "TextNarrativeParser"]
