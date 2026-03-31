from __future__ import annotations

import re

from .shared import NarrativeSegment, next_offset, normalize


def build_pasted_notes_segments(text: str, modality: str = "pasted_notes") -> list[NarrativeSegment]:
    segments: list[NarrativeSegment] = []
    cursor = 0
    section_label: str | None = None
    idx = 1
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":") and len(line) < 80:
            section_label = line[:-1].strip()
            continue
        block_type = "list_item" if re.match(r"^([-*+]|\d+\.)\s+", line) else "note_line"
        offsets = next_offset(text, raw_line, cursor)
        cursor = offsets["end"]
        segments.append(
            NarrativeSegment(
                segment_id=f"seg_{idx:04d}",
                block_type=block_type,
                text=line,
                normalized_text=normalize(line),
                modality=modality,
                source_offsets=offsets,
                section_label=section_label,
                tags=["pasted_notes"],
            )
        )
        idx += 1
    return segments
