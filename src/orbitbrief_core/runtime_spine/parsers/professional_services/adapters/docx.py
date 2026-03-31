from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .shared import NarrativeSegment, next_offset, normalize


def build_docx_segments(path: Path, modality: str = "docx") -> list[NarrativeSegment]:
    segments: list[NarrativeSegment] = []
    with zipfile.ZipFile(path, "r") as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    idx = 1
    cursor = 0
    full_text = ""
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            full_text += node.text
        if node.tag.endswith("}p"):
            full_text += "\n"
    for p in root.iter():
        if not p.tag.endswith("}p"):
            continue
        text_tokens: list[str] = []
        for child in p.iter():
            if child.tag.endswith("}t") and child.text:
                text_tokens.append(child.text)
        content = " ".join(text_tokens).strip()
        if not content:
            continue
        is_list = any(child.tag.endswith("}numPr") for child in p.iter())
        offsets = next_offset(full_text, content, cursor)
        cursor = offsets["end"]
        segments.append(
            NarrativeSegment(
                segment_id=f"seg_{idx:04d}",
                block_type="list_item" if is_list else "paragraph",
                text=content,
                normalized_text=normalize(content),
                modality=modality,
                source_offsets=offsets,
                tags=["docx", "list" if is_list else "body"],
            )
        )
        idx += 1
    return segments
