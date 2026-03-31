from __future__ import annotations

import re
from dataclasses import dataclass, field

from ....shared import normalize_whitespace


@dataclass(slots=True)
class NarrativeSegment:
    segment_id: str
    block_type: str
    text: str
    normalized_text: str
    modality: str
    source_offsets: dict[str, int]
    section_label: str | None = None
    sender_label: str | None = None
    message_index: int | None = None
    tags: list[str] = field(default_factory=list)


def next_offset(text: str, chunk: str, cursor: int) -> dict[str, int]:
    if not chunk:
        return {"start": cursor, "end": cursor}
    idx = text.find(chunk, cursor)
    if idx < 0:
        idx = text.find(chunk)
    if idx < 0:
        idx = cursor
    return {"start": idx, "end": idx + len(chunk)}


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r", "\n")) if p.strip()]


def normalize(text: str) -> str:
    return normalize_whitespace(text).lower()
