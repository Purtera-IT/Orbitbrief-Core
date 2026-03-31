from __future__ import annotations

from pathlib import Path

from ..file_utils import read_textual_file, sha256_file, split_paragraphs
from .models import ParsedArtifact, ParsedBlock


class TextNarrativeParser:
    parser_id = "text_narrative_parser"
    parser_version = "0.1.0"
    supported_modalities = {"txt", "md", "docx", "email_export", "pasted_notes"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        source_modality = "txt" if modality in {"email_export", "pasted_notes"} else modality
        text = read_textual_file(path, source_modality)
        blocks = [
            ParsedBlock(
                block_id=f"para_{idx+1}",
                block_type="paragraph",
                text=paragraph,
                confidence=0.9,
            )
            for idx, paragraph in enumerate(split_paragraphs(text))
            if paragraph.strip()
        ]
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=blocks,
            metadata={"block_count": len(blocks)},
        )
