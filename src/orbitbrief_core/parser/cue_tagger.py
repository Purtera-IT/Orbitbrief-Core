from __future__ import annotations

from dataclasses import replace

from orbitbrief_core.parser.shared.types import CueKind, DocumentParse

_CUE_HINTS: tuple[tuple[str, str], ...] = (
    ("scope", "scope_included"),
    ("exclude", "scope_excluded"),
    ("by others", "scope_by_others"),
    ("assumption", "assumption"),
    ("risk", "risk"),
    ("dependenc", "dependency"),
    ("deliverable", "deliverable"),
    ("acceptance", "acceptance"),
    ("customer", "customer_responsibility"),
    ("site", "site_location"),
    ("locations", "site_count"),
)


def _cue_enums_from_text(text: str) -> tuple[CueKind, ...]:
    out: list[CueKind] = []
    lower = text.lower()
    if any(token in lower for token in ("maybe", "might", "could", "possibly")):
        out.append(CueKind.HEDGE)
    if any(token in lower for token in ("will", "commit", "agreed", "shall")):
        out.append(CueKind.COMMITMENT)
    if "?" in text or any(token in lower for token in ("uncertain", "unknown")):
        out.append(CueKind.UNCERTAINTY)
    if any(token in lower for token in ("not ", "no ", "without", "exclude")):
        out.append(CueKind.NEGATION)
    if any(ch.isdigit() for ch in text):
        out.append(CueKind.QUANTITY)
    if any(token in lower for token in ("week", "month", "date", "schedule", "timeline")):
        out.append(CueKind.SCHEDULE)
    return tuple(dict.fromkeys(out))


def apply_cue_tags(document_parse: DocumentParse) -> tuple[DocumentParse, tuple[str, ...]]:
    diagnostics: list[str] = []
    spans = []
    for span in document_parse.evidence_spans:
        parser_cues: list[str] = []
        combined_text = f"{span.normalized_text} {' '.join(span.section_path)}".lower()
        for token, cue_name in _CUE_HINTS:
            if token in combined_text:
                parser_cues.append(cue_name)
        cue_enums = _cue_enums_from_text(span.text)
        if parser_cues or cue_enums:
            diagnostics.append(f"cue_tagged:{span.span_id}")
        meta = dict(span.metadata)
        if parser_cues:
            meta["parser_cues"] = sorted(set(parser_cues))
        spans.append(replace(span, cue_kinds=cue_enums, metadata=meta))

    return replace(document_parse, evidence_spans=tuple(spans)), tuple(diagnostics)
