from __future__ import annotations

from pathlib import Path

from ..file_utils import pdf_page_count, sha256_file
from .models import ParsedArtifact, ParsedBlock


class PdfOcrParser:
    parser_id = "pdf_ocr_parser"
    parser_version = "0.1.0"
    supported_modalities = {"image_pdf"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        # Placeholder until OCR engine is wired (Azure Vision / Document Intelligence / custom).
        page_count = pdf_page_count(path)
        block = ParsedBlock(
            block_id="ocr_placeholder_1",
            block_type="ocr_placeholder",
            text="[ocr_not_wired]",
            confidence=0.0,
            tags=["needs_ocr_backend"],
        )
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=[block],
            metadata={"page_count": page_count, "ocr_used": True, "status": "placeholder"},
        )
