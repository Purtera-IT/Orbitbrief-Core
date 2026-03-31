from __future__ import annotations

import re

from .shared import NarrativeSegment, next_offset, normalize


def build_md_segments(text: str, modality: str = "md") -> list[NarrativeSegment]:
    segments: list[NarrativeSegment] = []
    cursor = 0
    section_label: str | None = None
    idx = 1
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        block_type = "paragraph"
        tags = ["markdown"]
        if line.startswith("#"):
            block_type = "heading"
            section_label = line.lstrip("#").strip() or section_label
            tags.append("section_heading")
        elif re.match(r"^([-*+]|\d+\.)\s+", line):
            block_type = "list_item"
            tags.append("bullet")
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
                tags=tags,
            )
        )
        idx += 1
    return segments
