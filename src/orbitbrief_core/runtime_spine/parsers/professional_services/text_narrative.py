from __future__ import annotations

from pathlib import Path

from ...file_utils import read_textual_file, sha256_file, split_paragraphs
from ..models import ParsedArtifact, ParsedBlock
from .adapters import build_narrative_segments
from .contracts import TEXT_NARRATIVE_PARSER_IO_VERSION


class TextNarrativeParser:
    parser_id = "text_narrative_parser"
    parser_version = "1.0.0"
    supported_modalities = {"txt", "md", "docx", "email_export", "pasted_notes"}

    def parse(self, path: Path, modality: str, role_hint: str | None = None) -> ParsedArtifact:
        source_modality = "txt" if modality in {"email_export", "pasted_notes"} else modality
        text = read_textual_file(path, source_modality)
        segments = build_narrative_segments(path, modality, text)
        blocks = []
        for seg in segments:
            blocks.append(
                ParsedBlock(
                    block_id=seg.segment_id,
                    block_type=seg.block_type,
                    text=seg.text,
                    normalized_text=seg.normalized_text,
                    confidence=0.9,
                    tags=list(seg.tags),
                    metadata={
                        "section_label": seg.section_label,
                        "sender_label": seg.sender_label,
                        "message_index": seg.message_index,
                        "source_offsets": seg.source_offsets,
                        "modality": seg.modality,
                    },
                )
            )
        if not blocks:
            for idx, paragraph in enumerate(split_paragraphs(text), start=1):
                if not paragraph.strip():
                    continue
                blocks.append(
                    ParsedBlock(
                        block_id=f"para_{idx}",
                        block_type="paragraph",
                        text=paragraph,
                        normalized_text=paragraph.strip().lower(),
                        confidence=0.8,
                    )
                )
        return ParsedArtifact(
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            role_hint=role_hint,
            modality=modality,
            source_path=str(path),
            source_hash=sha256_file(path),
            blocks=blocks,
            metadata={
                "io_version": TEXT_NARRATIVE_PARSER_IO_VERSION,
                "block_count": len(blocks),
                "modality": modality,
                "parser_group": "professional_services",
            },
        )
