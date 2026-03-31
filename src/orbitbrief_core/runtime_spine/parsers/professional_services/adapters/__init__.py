from __future__ import annotations

from pathlib import Path

from .docx import build_docx_segments
from .email_export import build_email_export_segments
from .md import build_md_segments
from .pasted_notes import build_pasted_notes_segments
from .shared import NarrativeSegment
from .txt import build_txt_segments


def build_narrative_segments(path: Path, modality: str, raw_text: str) -> list[NarrativeSegment]:
    if modality == "md":
        return build_md_segments(raw_text, modality)
    if modality == "docx":
        return build_docx_segments(path, modality)
    if modality == "email_export":
        return build_email_export_segments(raw_text, modality)
    if modality == "pasted_notes":
        return build_pasted_notes_segments(raw_text, modality)
    return build_txt_segments(raw_text, modality)


__all__ = [
    "NarrativeSegment",
    "build_docx_segments",
    "build_email_export_segments",
    "build_md_segments",
    "build_narrative_segments",
    "build_pasted_notes_segments",
    "build_txt_segments",
]
