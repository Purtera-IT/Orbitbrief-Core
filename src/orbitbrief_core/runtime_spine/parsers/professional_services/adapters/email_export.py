from __future__ import annotations

from .shared import NarrativeSegment, next_offset, normalize, paragraphs


def _email_clean_lines(text: str) -> tuple[list[str], list[str]]:
    lines = text.replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    senders: list[str] = []
    current_sender: str | None = None
    for line in lines:
        raw = line.rstrip()
        lower = raw.lower().strip()
        if not lower:
            cleaned.append("")
            senders.append(current_sender or "")
            continue
        if lower.startswith("from:"):
            current_sender = raw.split(":", 1)[1].strip()
            continue
        if lower.startswith("on ") and " wrote:" in lower:
            break
        if raw.startswith(">"):
            continue
        if lower in {"--", "__"} or lower.startswith("sent from my"):
            break
        cleaned.append(raw)
        senders.append(current_sender or "")
    return cleaned, senders


def build_email_export_segments(text: str, modality: str = "email_export") -> list[NarrativeSegment]:
    cleaned_lines, senders = _email_clean_lines(text)
    cleaned_text = "\n".join(cleaned_lines)
    segments: list[NarrativeSegment] = []
    cursor = 0
    for idx, paragraph in enumerate(paragraphs(cleaned_text), start=1):
        offsets = next_offset(cleaned_text, paragraph, cursor)
        cursor = offsets["end"]
        sender_label = None
        if senders:
            line_idx = cleaned_text[: offsets["start"]].count("\n")
            sender_label = senders[min(line_idx, len(senders) - 1)] or None
        segments.append(
            NarrativeSegment(
                segment_id=f"seg_{idx:04d}",
                block_type="message_paragraph",
                text=paragraph,
                normalized_text=normalize(paragraph),
                modality=modality,
                source_offsets=offsets,
                sender_label=sender_label,
                message_index=idx,
                tags=["email", "cleaned"],
            )
        )
    return segments
