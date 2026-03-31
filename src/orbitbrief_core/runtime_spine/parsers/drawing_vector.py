from __future__ import annotations

from pathlib import Path

from ..file_utils import sha256_file
from .models import ParsedArtifact, ParsedBlock


class DrawingVectorParser:
    parser_id = "drawing_vector_parser"
    parser_version = "0.1.0"
    supported_modalities = {"dwg_export_pdf", "esx", "cad"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        block = ParsedBlock(
            block_id="vector_placeholder_1",
            block_type="vector_placeholder",
            text="[vector_parser_not_wired]",
            confidence=0.0,
            tags=["needs_vector_backend"],
        )
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=[block],
            metadata={"status": "placeholder"},
        )
