from __future__ import annotations

import re
from typing import Any, Iterable

from orbitbrief_core.parser.shared.types import EvidenceSpan

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/&']+")
_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|except|excluding|exclude|won't|cannot|can't|outside)\b", re.I)
_NUMERIC_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_QUOTE_KIND_RE = re.compile(r"quoted_context|forwarded_context|signature|disclaimer", re.I)


def lexical_tokens(text: str) -> tuple[str, ...]:
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    return tuple(token for token in tokens if len(token) > 1)


def jaccard_similarity(a: str, b: str) -> float:
    aset = set(lexical_tokens(a))
    bset = set(lexical_tokens(b))
    if not aset or not bset:
        return 0.0
    return len(aset & bset) / len(aset | bset)


def span_has_question(span: EvidenceSpan) -> bool:
    text = span.text.lower()
    return "?" in span.text or any(token in text for token in ("tbd", "unknown", "open question", "confirm"))


def span_has_decision_language(span: EvidenceSpan) -> bool:
    text = span.normalized_text.lower()
    return any(token in text for token in ("agreed", "decided", "decision", "will proceed", "action item", "owner:"))


def cue_kinds_for_textish(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    out: list[str] = []
    hints = (
        ("scope", "scope_included"),
        ("exclude", "scope_excluded"),
        ("assumption", "assumption"),
        ("risk", "risk"),
        ("dependenc", "dependency"),
        ("deliverable", "deliverable"),
        ("acceptance", "acceptance"),
        ("customer", "customer_responsibility"),
        ("site", "site_location"),
        ("schedule", "schedule"),
        ("question", "open_question"),
    )
    for token, cue in hints:
        if token in lowered and cue not in out:
            out.append(cue)
    return tuple(out)


def normalized_cue_values(values: Iterable[Any]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = getattr(value, "value", value)
        text = str(text).strip()
        if not text or text in seen:
            continue
        ordered.append(text)
        seen.add(text)
    return tuple(ordered)


def derive_span_cues(span: EvidenceSpan) -> tuple[str, ...]:
    if span.cue_kinds:
        return normalized_cue_values(span.cue_kinds)
    return normalized_cue_values(cue_kinds_for_textish(span.normalized_text))


def lexical_similarity(left: EvidenceSpan, right: EvidenceSpan) -> float:
    return jaccard_similarity(left.normalized_text, right.normalized_text)


def cue_overlap(left: EvidenceSpan, right: EvidenceSpan) -> float:
    left_cues = set(derive_span_cues(left))
    right_cues = set(derive_span_cues(right))
    if not left_cues or not right_cues:
        return 0.0
    return len(left_cues & right_cues) / len(left_cues | right_cues)


def shared_token_count(left: EvidenceSpan, right: EvidenceSpan) -> int:
    return len(set(lexical_tokens(left.normalized_text)) & set(lexical_tokens(right.normalized_text)))


def numeric_fingerprint(text: str) -> tuple[str, ...]:
    return tuple(_NUMERIC_RE.findall(text))


def contradiction_score(left: EvidenceSpan, right: EvidenceSpan) -> float:
    left_tokens = set(lexical_tokens(left.normalized_text))
    right_tokens = set(lexical_tokens(right.normalized_text))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    negation_bonus = 0.25 if bool(_NEGATION_RE.search(left.text)) != bool(_NEGATION_RE.search(right.text)) else 0.0
    numeric_bonus = 0.18 if numeric_fingerprint(left.text) and numeric_fingerprint(right.text) and numeric_fingerprint(left.text) != numeric_fingerprint(right.text) else 0.0
    question_penalty = 0.18 if span_has_question(left) or span_has_question(right) else 0.0
    return max(0.0, min(1.0, overlap + negation_bonus + numeric_bonus - question_penalty))


def support_score(left: EvidenceSpan, right: EvidenceSpan) -> float:
    lexical = lexical_similarity(left, right)
    cue = cue_overlap(left, right)
    shared = min(0.25, shared_token_count(left, right) * 0.04)
    decision_bonus = 0.12 if span_has_decision_language(left) or span_has_decision_language(right) else 0.0
    return max(0.0, min(1.0, lexical * 0.45 + cue * 0.35 + shared + decision_bonus))


def section_affinity(left: EvidenceSpan, right: EvidenceSpan) -> float:
    if tuple(left.section_path) == tuple(right.section_path):
        return 1.0
    if left.section_path and right.section_path and tuple(left.section_path[:-1]) == tuple(right.section_path[:-1]):
        return 0.66
    return 0.0


def span_noise_hint(span: EvidenceSpan) -> bool:
    kind = str(span.metadata.get("kind", ""))
    if _QUOTE_KIND_RE.search(kind):
        return True
    return span.authority_score < 0.25


def span_position_distance(left: EvidenceSpan, right: EvidenceSpan) -> int:
    if left.chronology_rank is not None and right.chronology_rank is not None:
        return abs(left.chronology_rank - right.chronology_rank)
    if left.char_range is not None and right.char_range is not None:
        return abs(left.char_range.start - right.char_range.start)
    return 999999


_PACKET_FAMILY_BY_CUE = {
    "scope_included": ("scope_packet",),
    "scope_excluded": ("exclusion_packet",),
    "scope_by_others": ("exclusion_packet", "dependency_packet"),
    "assumption": ("assumption_packet",),
    "risk": ("risk_packet",),
    "dependency": ("dependency_packet",),
    "deliverable": ("deliverable_packet",),
    "acceptance": ("deliverable_packet",),
    "customer_responsibility": ("responsibility_packet",),
    "site_location": ("site_packet",),
    "site_count": ("quantity_packet", "site_packet"),
    "schedule": ("schedule_packet",),
    "open_question": ("open_question_packet",),
}


def packet_families_for_span(span: EvidenceSpan) -> tuple[str, ...]:
    cue_values = derive_span_cues(span)
    families: list[str] = []
    seen: set[str] = set()
    for cue in cue_values:
        for family in _PACKET_FAMILY_BY_CUE.get(cue, ()):
            if family not in seen:
                families.append(family)
                seen.add(family)
    if not families and span_has_question(span):
        families.append("open_question_packet")
    if not families and span_has_decision_language(span):
        families.append("scope_packet")
    return tuple(families)


def packet_seed_score(
    span: EvidenceSpan,
    *,
    neighborhood_support: float,
    neighborhood_same_topic: float,
    hook: Any | None = None,
) -> float:
    cue_bonus = min(0.32, len(derive_span_cues(span)) * 0.08)
    authority = max(0.0, min(1.0, span.authority_score))
    question_bonus = 0.12 if span_has_question(span) else 0.0
    decision_bonus = 0.08 if span_has_decision_language(span) else 0.0
    noise_penalty = 0.18 if span_noise_hint(span) else 0.0
    base = authority * 0.38 + neighborhood_support * 0.28 + neighborhood_same_topic * 0.16 + cue_bonus + question_bonus + decision_bonus - noise_penalty
    if hook is not None:
        maybe = hook(
            node=span,
            features={
                "cue_bonus": cue_bonus,
                "authority": authority,
                "question_bonus": question_bonus,
                "decision_bonus": decision_bonus,
                "noise_penalty": noise_penalty,
                "neighborhood_support": neighborhood_support,
                "neighborhood_same_topic": neighborhood_same_topic,
            },
        )
        if maybe is not None:
            base = (base * 0.65) + (float(maybe) * 0.35)
    return max(0.0, min(1.0, base))
