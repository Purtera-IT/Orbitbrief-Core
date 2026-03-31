from __future__ import annotations

import re

from .shared import NarrativeSegment, next_offset, normalize, paragraphs


def build_txt_segments(text: str, modality: str = "txt") -> list[NarrativeSegment]:
    segments: list[NarrativeSegment] = []
    cursor = 0
    for idx, paragraph in enumerate(paragraphs(text), start=1):
        block_type = "list_item" if re.match(r"^([-*+]|\d+\.)\s+", paragraph) else "paragraph"
        offsets = next_offset(text, paragraph, cursor)
        cursor = offsets["end"]
        segments.append(
            NarrativeSegment(
                segment_id=f"seg_{idx:04d}",
                block_type=block_type,
                text=paragraph,
                normalized_text=normalize(paragraph),
                modality=modality,
                source_offsets=offsets,
                tags=["txt_like"],
            )
        )
    return segments
