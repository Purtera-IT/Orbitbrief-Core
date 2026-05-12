from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.shared.types import DiscourseType


_UNICODE_TRANSLATIONS = str.maketrans(
    {
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u25cf": "-",
        "\u25e6": "-",
        "\u2212": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\t": "    ",
    }
)

_BULLET_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>[-*•◦▪‣]|\d+[.)]|[A-Za-z][.)])\s+(?P<body>\S.*)$")
_MD_HEADING_RE = re.compile(r"^\s{0,3}(?P<hash>#{1,6})\s+(?P<title>\S.*)$")
_NUMBERED_HEADING_RE = re.compile(r"^(?P<num>(?:\d+\.)+\d*|\d+)[)\.]?\s+(?P<title>[A-Z][^\n]{1,120})$")
_SPEAKER_RE = re.compile(
    r"^(?:(?P<time>\[?\b(?:[01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?\]?)[\s\-]*)?"
    r"(?P<speaker>[A-Z][A-Za-z0-9 .&'\-/]{1,60})\s*:\s*(?P<body>.+)$"
)
_TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?\b")
_ACTION_RE = re.compile(r"\b(action item|owner|eta|next step|todo|follow[- ]?up)\b", re.I)
_MEMO_HEADINGS = {
    "scope",
    "summary",
    "assumptions",
    "deliverables",
    "exclusions",
    "schedule",
    "responsibilities",
    "dependencies",
    "risks",
    "site list",
    "customer responsibilities",
    "testing",
    "acceptance",
    "open questions",
}


@dataclass(frozen=True, slots=True)
class RawLine:
    line_id: str
    text: str
    normalized_text: str
    char_start: int
    char_end: int
    line_index: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParagraphCandidate:
    paragraph_id: str
    line_ids: tuple[str, ...]
    text: str
    normalized_text: str
    start_char: int
    end_char: int
    paragraph_index: int
    kind: str = "paragraph"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BulletCandidate:
    bullet_id: str
    line_ids: tuple[str, ...]
    text: str
    normalized_text: str
    start_char: int
    end_char: int
    bullet_index: int
    level: int = 1
    marker: str = "-"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpeakerTurnCandidate:
    turn_id: str
    line_ids: tuple[str, ...]
    speaker_label: str
    text: str
    normalized_text: str
    start_char: int
    end_char: int
    turn_index: int
    time_text: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeadingCandidate:
    heading_id: str
    line_ids: tuple[str, ...]
    title: str
    normalized_title: str
    start_char: int
    end_char: int
    heading_index: int
    level: int = 1
    style: str = "heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TextSegmentationResult:
    normalized_text: str
    raw_lines: tuple[RawLine, ...]
    headings: tuple[HeadingCandidate, ...]
    paragraphs: tuple[ParagraphCandidate, ...]
    bullets: tuple[BulletCandidate, ...]
    speaker_turns: tuple[SpeakerTurnCandidate, ...]
    diagnostics: tuple[str, ...] = ()


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").translate(_UNICODE_TRANSLATIONS)
    normalized = re.sub(r"[ ]{3,}", "  ", normalized)
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized


def normalize_text_lines(text: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in normalize_text(text).split("\n"))


def infer_heading_strength(text: str) -> float:
    value = str(text or "").strip()
    if not value:
        return 0.0
    if _MD_HEADING_RE.match(value):
        return 1.0
    lowered = value.rstrip(":").lower()
    if lowered in _MEMO_HEADINGS:
        return 0.9
    if _NUMBERED_HEADING_RE.match(value):
        return 0.86
    words = value.rstrip(":").split()
    if len(words) <= 8 and value.endswith(":"):
        return 0.76
    if value.isupper() and 2 <= len(words) <= 8:
        return 0.72
    if 1 <= len(words) <= 6 and sum(1 for token in words if token[:1].isupper()) >= max(1, len(words) - 1):
        return 0.64
    return 0.2


def build_ambiguity_metadata(
    *,
    ambiguity_tags: Sequence[str] | None = None,
    candidate_section_break: bool = False,
    candidate_heading_strength: float | None = None,
    candidate_list_parent_span_id: str | None = None,
    candidate_neighborhood_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ambiguity_tags": list(ambiguity_tags or ()),
        "candidate_section_break": bool(candidate_section_break),
        "candidate_list_parent_span_id": candidate_list_parent_span_id,
        "candidate_neighborhood_ids": list(candidate_neighborhood_ids or ()),
    }
    if candidate_heading_strength is not None:
        metadata["candidate_heading_strength"] = round(float(candidate_heading_strength), 3)
    return metadata


def detect_list_block(line: RawLine) -> tuple[str, int, str, str] | None:
    match = _BULLET_RE.match(line.text)
    if not match:
        return None
    indent = len(match.group("indent"))
    level = 1 + indent // 2
    marker = match.group("marker")
    body = match.group("body").strip()
    kind = "numbered_item" if marker[:1].isdigit() else "bullet"
    return (kind, level, marker, body)


def candidate_section_breaks(lines: Sequence[RawLine]) -> tuple[int, ...]:
    breaks: list[int] = []
    for idx, line in enumerate(lines):
        if not line.normalized_text:
            continue
        strength = infer_heading_strength(line.text)
        prev_blank = idx == 0 or not lines[idx - 1].normalized_text
        next_blank = idx == len(lines) - 1 or not lines[idx + 1].normalized_text
        if strength >= 0.6 and (prev_blank or next_blank):
            breaks.append(line.line_index)
    return tuple(breaks)


def build_raw_lines(text: str) -> tuple[RawLine, ...]:
    lines: list[RawLine] = []
    cursor = 0
    for idx, line in enumerate(text.splitlines(keepends=True)):
        line_text = line.rstrip("\n")
        normalized = line_text.strip()
        char_start = cursor
        char_end = cursor + len(line_text)
        lines.append(
            RawLine(
                line_id=f"line:{idx:06d}",
                text=line_text,
                normalized_text=normalized,
                char_start=char_start,
                char_end=char_end,
                line_index=idx,
            )
        )
        cursor += len(line)
    return tuple(lines)


def _heading_level_from_text(text: str) -> int:
    md_match = _MD_HEADING_RE.match(text)
    if md_match:
        return len(md_match.group("hash"))
    numbered = _NUMBERED_HEADING_RE.match(text.strip())
    if numbered:
        num = numbered.group("num")
        return max(1, num.count(".") + 1)
    return 1


def detect_heading(line: RawLine) -> HeadingCandidate | None:
    text = line.text.strip()
    if not text:
        return None
    md_match = _MD_HEADING_RE.match(text)
    if md_match:
        title = md_match.group("title").strip()
        return HeadingCandidate(
            heading_id=f"heading:{line.line_index:06d}",
            line_ids=(line.line_id,),
            title=title,
            normalized_title=title.lower(),
            start_char=line.char_start,
            end_char=line.char_end,
            heading_index=line.line_index,
            level=len(md_match.group("hash")),
            style="markdown",
            metadata=build_ambiguity_metadata(candidate_heading_strength=1.0),
        )
    stripped = text.rstrip(":")
    lowered = stripped.lower()
    if lowered in _MEMO_HEADINGS:
        return HeadingCandidate(
            heading_id=f"heading:{line.line_index:06d}",
            line_ids=(line.line_id,),
            title=stripped,
            normalized_title=lowered,
            start_char=line.char_start,
            end_char=line.char_end,
            heading_index=line.line_index,
            level=_heading_level_from_text(stripped),
            style="memo_heading",
            metadata=build_ambiguity_metadata(candidate_heading_strength=0.9),
        )
    numbered = _NUMBERED_HEADING_RE.match(text)
    if numbered:
        title = numbered.group("title").strip().rstrip(":")
        strength = infer_heading_strength(text)
        return HeadingCandidate(
            heading_id=f"heading:{line.line_index:06d}",
            line_ids=(line.line_id,),
            title=title,
            normalized_title=title.lower(),
            start_char=line.char_start,
            end_char=line.char_end,
            heading_index=line.line_index,
            level=_heading_level_from_text(text),
            style="numbered",
            metadata=build_ambiguity_metadata(
                candidate_heading_strength=strength,
                ambiguity_tags=("ambiguous_heading_candidate",) if strength < 0.9 else (),
            ),
        )
    if text.isupper() and 2 <= len(text.split()) <= 8 and len(text) <= 80:
        title = text.title()
        strength = infer_heading_strength(text)
        return HeadingCandidate(
            heading_id=f"heading:{line.line_index:06d}",
            line_ids=(line.line_id,),
            title=title,
            normalized_title=title.lower(),
            start_char=line.char_start,
            end_char=line.char_end,
            heading_index=line.line_index,
            level=1,
            style="all_caps",
            metadata=build_ambiguity_metadata(
                candidate_heading_strength=strength,
                ambiguity_tags=("ambiguous_heading_candidate",),
            ),
        )
    return None


def detect_bullet(line: RawLine) -> BulletCandidate | None:
    list_candidate = detect_list_block(line)
    if list_candidate is None:
        return None
    kind, level, marker, body = list_candidate
    is_numbered = kind == "numbered_item"
    return BulletCandidate(
        bullet_id=f"bullet:{line.line_index:06d}",
        line_ids=(line.line_id,),
        text=body,
        normalized_text=body,
        start_char=line.char_start,
        end_char=line.char_end,
        bullet_index=line.line_index,
        level=level,
        marker=marker,
        metadata=build_ambiguity_metadata(
            ambiguity_tags=() if level == 1 else ("ambiguous_list_parent_candidate",),
            candidate_list_parent_span_id=None,
        )
        | {"indent": max(0, (level - 1) * 2), "list_kind": kind, "numbered": is_numbered},
    )


def detect_speaker_turn(line: RawLine) -> SpeakerTurnCandidate | None:
    match = _SPEAKER_RE.match(line.text.strip())
    if not match:
        return None
    speaker = match.group("speaker").strip()
    body = match.group("body").strip()
    time_text = match.group("time")
    return SpeakerTurnCandidate(
        turn_id=f"turn:{line.line_index:06d}",
        line_ids=(line.line_id,),
        speaker_label=speaker,
        text=body,
        normalized_text=body,
        start_char=line.char_start,
        end_char=line.char_end,
        turn_index=line.line_index,
        time_text=time_text,
        metadata={"line_index": line.line_index},
    )


def _merge_speaker_turns(lines: Sequence[RawLine], detected: dict[int, SpeakerTurnCandidate]) -> tuple[SpeakerTurnCandidate, ...]:
    turns: list[SpeakerTurnCandidate] = []
    current: SpeakerTurnCandidate | None = None
    for line in lines:
        candidate = detected.get(line.line_index)
        if candidate is not None:
            if current is not None:
                turns.append(current)
            current = candidate
            continue
        if current is None:
            continue
        if not line.normalized_text:
            turns.append(current)
            current = None
            continue
        updated_lines = current.line_ids + (line.line_id,)
        updated_text = f"{current.text} {line.normalized_text}".strip()
        current = SpeakerTurnCandidate(
            turn_id=current.turn_id,
            line_ids=updated_lines,
            speaker_label=current.speaker_label,
            text=updated_text,
            normalized_text=updated_text,
            start_char=current.start_char,
            end_char=line.char_end,
            turn_index=current.turn_index,
            time_text=current.time_text,
            metadata=dict(current.metadata),
        )
    if current is not None:
        turns.append(current)
    return tuple(turns)


def _build_paragraphs(
    lines: Sequence[RawLine],
    occupied_lines: set[int],
    *,
    section_break_lines: set[int] | None = None,
) -> tuple[ParagraphCandidate, ...]:
    paragraphs: list[ParagraphCandidate] = []
    current_lines: list[RawLine] = []
    paragraph_index = 0
    section_break_lines = section_break_lines or set()
    for line in lines:
        if line.line_index in occupied_lines:
            if current_lines:
                paragraphs.append(
                    _paragraph_from_lines(
                        current_lines,
                        paragraph_index,
                        candidate_section_break=current_lines[0].line_index in section_break_lines,
                    )
                )
                paragraph_index += 1
                current_lines = []
            continue
        if not line.normalized_text:
            if current_lines:
                paragraphs.append(
                    _paragraph_from_lines(
                        current_lines,
                        paragraph_index,
                        candidate_section_break=current_lines[0].line_index in section_break_lines,
                    )
                )
                paragraph_index += 1
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(
            _paragraph_from_lines(
                current_lines,
                paragraph_index,
                candidate_section_break=current_lines[0].line_index in section_break_lines,
            )
        )
    enriched: list[ParagraphCandidate] = []
    for idx, paragraph in enumerate(paragraphs):
        neighborhood: list[str] = []
        if idx > 0:
            neighborhood.append(paragraphs[idx - 1].paragraph_id)
        if idx + 1 < len(paragraphs):
            neighborhood.append(paragraphs[idx + 1].paragraph_id)
        metadata = dict(paragraph.metadata)
        existing_tags = list(metadata.get("ambiguity_tags", []))
        metadata.update(
            build_ambiguity_metadata(
                ambiguity_tags=existing_tags,
                candidate_section_break=bool(metadata.get("candidate_section_break", False)),
                candidate_heading_strength=metadata.get("candidate_heading_strength"),
                candidate_list_parent_span_id=metadata.get("candidate_list_parent_span_id"),
                candidate_neighborhood_ids=neighborhood,
            )
        )
        enriched.append(
            ParagraphCandidate(
                paragraph_id=paragraph.paragraph_id,
                line_ids=paragraph.line_ids,
                text=paragraph.text,
                normalized_text=paragraph.normalized_text,
                start_char=paragraph.start_char,
                end_char=paragraph.end_char,
                paragraph_index=paragraph.paragraph_index,
                kind=paragraph.kind,
                metadata=metadata,
            )
        )
    return tuple(enriched)


def _paragraph_from_lines(
    lines: Sequence[RawLine],
    paragraph_index: int,
    *,
    candidate_section_break: bool,
) -> ParagraphCandidate:
    text = " ".join(line.normalized_text for line in lines if line.normalized_text).strip()
    kind = "paragraph"
    if _ACTION_RE.search(text):
        kind = "action_item"
    heading_strength = infer_heading_strength(lines[0].text if lines else text)
    ambiguity_tags: list[str] = []
    if kind == "paragraph" and 0.58 <= heading_strength < 0.8 and len(lines) <= 2:
        ambiguity_tags.append("ambiguous_heading_candidate")
    return ParagraphCandidate(
        paragraph_id=f"para:{paragraph_index:06d}",
        line_ids=tuple(line.line_id for line in lines),
        text=text,
        normalized_text=text,
        start_char=lines[0].char_start,
        end_char=lines[-1].char_end,
        paragraph_index=paragraph_index,
        kind=kind,
        metadata={"line_count": len(lines)}
        | build_ambiguity_metadata(
            ambiguity_tags=tuple(ambiguity_tags),
            candidate_section_break=candidate_section_break,
            candidate_heading_strength=heading_strength,
        ),
    )


def segment_text(text: str, *, discourse_type: DiscourseType | None = None) -> TextSegmentationResult:
    normalized = normalize_text(text)
    raw_lines = build_raw_lines(normalized)
    headings: list[HeadingCandidate] = []
    bullets: list[BulletCandidate] = []
    speaker_candidates: dict[int, SpeakerTurnCandidate] = {}
    diagnostics: list[str] = []
    occupied_line_indexes: set[int] = set()

    for line in raw_lines:
        heading = detect_heading(line)
        speaker_turn = detect_speaker_turn(line)
        bullet = detect_bullet(line)

        if discourse_type is DiscourseType.CALL_TRANSCRIPT and speaker_turn is not None:
            speaker_candidates[line.line_index] = speaker_turn
            occupied_line_indexes.add(line.line_index)
            continue

        if heading is not None:
            headings.append(heading)
            occupied_line_indexes.add(line.line_index)
            continue

        if bullet is not None:
            bullets.append(bullet)
            occupied_line_indexes.add(line.line_index)
            continue

        if discourse_type is not DiscourseType.CALL_TRANSCRIPT and speaker_turn is not None:
            speaker_candidates[line.line_index] = speaker_turn
            occupied_line_indexes.add(line.line_index)

    speaker_turns = _merge_speaker_turns(raw_lines, speaker_candidates)
    for turn in speaker_turns:
        for line_id in turn.line_ids:
            if line_id.startswith("line:"):
                occupied_line_indexes.add(int(line_id.split(":", 1)[1]))

    break_lines = set(candidate_section_breaks(raw_lines))
    paragraphs = _build_paragraphs(raw_lines, occupied_line_indexes, section_break_lines=break_lines)

    if discourse_type is DiscourseType.CALL_TRANSCRIPT and not speaker_turns:
        diagnostics.append("call_transcript_requested_but_no_speaker_turns_detected")
    if discourse_type is DiscourseType.PROJECT_MEMO and not headings:
        diagnostics.append("project_memo_requested_but_no_headings_detected")

    return TextSegmentationResult(
        normalized_text=normalized,
        raw_lines=raw_lines,
        headings=tuple(headings),
        paragraphs=paragraphs,
        bullets=tuple(bullets),
        speaker_turns=speaker_turns,
        diagnostics=tuple(diagnostics),
    )


def heading_section_stack(headings: Sequence[HeadingCandidate]) -> list[HeadingCandidate]:
    return sorted(headings, key=lambda item: (item.start_char, item.level, item.heading_id))


def infer_heading_level(title: str) -> int:
    return _heading_level_from_text(title)


def extract_time_strings(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0) for match in _TIME_RE.finditer(text)))
