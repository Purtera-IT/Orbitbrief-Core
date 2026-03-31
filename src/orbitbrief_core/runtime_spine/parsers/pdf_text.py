from __future__ import annotations

from pathlib import Path

from ..file_utils import extract_pdf_text, pdf_page_count, sha256_file
from .models import ParsedArtifact, ParsedBlock


class PdfTextParser:
    parser_id = "pdf_text_parser"
    parser_version = "0.1.0"
    supported_modalities = {"pdf"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        text = extract_pdf_text(path)
        page_count = pdf_page_count(path)
        block = ParsedBlock(block_id="pdf_text_1", block_type="pdf_text", text=text, confidence=0.8)
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=[block],
            metadata={"page_count": page_count, "ocr_used": False},
        )
