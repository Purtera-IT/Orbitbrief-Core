from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from orbitbrief_core.parser.graph.indices import GraphIndices
from orbitbrief_core.parser.graph.neural_hooks import PacketSeedRequest
from orbitbrief_core.parser.shared.types import DocumentParse
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
    "sheet_ref": ("drawing_metadata_packet",),
    "sheet_title": ("drawing_metadata_packet",),
    "title_block_field": ("drawing_metadata_packet", "site_identity_packet"),
    "revision_entry": ("revision_change_packet",),
    "visual_region": ("drawing_metadata_packet",),
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
        features = {
            "cue_bonus": cue_bonus,
            "authority": authority,
            "question_bonus": question_bonus,
            "decision_bonus": decision_bonus,
            "noise_penalty": noise_penalty,
            "neighborhood_support": neighborhood_support,
            "neighborhood_same_topic": neighborhood_same_topic,
        }
        maybe: float | None = None
        if hasattr(hook, "score"):
            result = hook.score(
                PacketSeedRequest(
                    span_id=span.span_id,
                    text=span.normalized_text,
                    family_hints=packet_families_for_span(span),
                    authority_class=span.authority_class.value,
                    authority_score=authority,
                    local_support_density=neighborhood_support,
                    cue_strength=cue_bonus,
                    signals={key: float(value) for key, value in features.items()},
                )
            )
            if not getattr(result, "abstained", False):
                maybe = float(getattr(result, "score", 0.0))
        else:
            maybe = hook(node=span, features=features)
        if maybe is not None:
            base = (base * 0.65) + (max(0.0, min(1.0, float(maybe))) * 0.35)
    return max(0.0, min(1.0, base))


@dataclass(frozen=True, slots=True)
class LayoutSignals:
    same_page: bool
    page_distance: int | None
    bbox_vertical_proximity: float | None
    compatible: bool


@dataclass(frozen=True, slots=True)
class AuthoritySignals:
    same_author_id: bool
    same_speaker_id: bool
    same_actor_exact: bool
    same_actor_alias: bool
    boundary_class_left: str | None
    boundary_class_right: str | None
    authority_delta: float
    quoted_or_forwarded_mismatch: bool
    compatible: bool


@dataclass(frozen=True, slots=True)
class ChronologySignals:
    both_ranked: bool
    chronology_distance: int | None
    same_time_anchor: bool
    explicit_time_pair: bool
    temporal_order: bool
    chronology_near: bool


@dataclass(frozen=True, slots=True)
class CueSignals:
    left_cues: tuple[str, ...]
    right_cues: tuple[str, ...]
    cue_similarity: float
    shared_cues: tuple[str, ...]
    lexical_cue_overlap: float
    compatible: bool


@dataclass(frozen=True, slots=True)
class PairSignals:
    lexical_overlap: float
    section_distance: int | None
    same_actor: bool
    same_message: bool
    chronology_distance: int | None
    chronology_near: bool
    authority_compatible: bool
    cue_similarity: float
    ocr_confidence_compatibility: float | None
    ocr_weak_pair: bool


@dataclass(slots=True)
class GraphSignals:
    """Reusable deterministic feature service for graph passes and scorers."""

    parse: DocumentParse
    indices: GraphIndices
    _pair_cache: dict[tuple[str, str], PairSignals] = field(default_factory=dict, init=False, repr=False)
    _authority_cache: dict[tuple[str, str], AuthoritySignals] = field(default_factory=dict, init=False, repr=False)
    _chronology_cache: dict[tuple[str, str], ChronologySignals] = field(default_factory=dict, init=False, repr=False)
    _cue_cache: dict[tuple[str, str], CueSignals] = field(default_factory=dict, init=False, repr=False)
    _layout_cache: dict[tuple[str, str], LayoutSignals] = field(default_factory=dict, init=False, repr=False)

    def _span(self, span_id: str) -> EvidenceSpan:
        return self.indices.spans_by_id[span_id]

    @staticmethod
    def _cache_key(left_id: str, right_id: str) -> tuple[str, str]:
        return (left_id, right_id)

    @staticmethod
    def _symmetric_key(left_id: str, right_id: str) -> tuple[str, str]:
        return (left_id, right_id) if left_id <= right_id else (right_id, left_id)

    @staticmethod
    def _section_distance(left: EvidenceSpan, right: EvidenceSpan) -> int | None:
        left_path = tuple(left.section_path)
        right_path = tuple(right.section_path)
        if not left_path and not right_path:
            return None
        if left_path == right_path:
            return 0
        common = 0
        for l_part, r_part in zip(left_path, right_path):
            if l_part != r_part:
                break
            common += 1
        return (len(left_path) - common) + (len(right_path) - common)

    @staticmethod
    def _ocr_compatibility(left: EvidenceSpan, right: EvidenceSpan) -> tuple[float | None, bool]:
        def _read(value: Any) -> float | None:
            try:
                if value is None:
                    return None
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return None

        left_conf = _read(left.metadata.get("ocr_confidence"))
        right_conf = _read(right.metadata.get("ocr_confidence"))
        if left_conf is None or right_conf is None:
            return None, False
        compatibility = max(0.0, 1.0 - abs(left_conf - right_conf))
        weak_pair = left_conf < 0.45 or right_conf < 0.45
        return compatibility, weak_pair

    @staticmethod
    def _actor_alias_match(left: EvidenceSpan, right: EvidenceSpan) -> bool:
        left_label = str(left.metadata.get("speaker_label", "")).strip().lower()
        right_label = str(right.metadata.get("speaker_label", "")).strip().lower()
        if not left_label or not right_label:
            return False
        if left_label == right_label:
            return True
        left_tokens = set(left_label.split())
        right_tokens = set(right_label.split())
        return bool(left_tokens and right_tokens and left_tokens == right_tokens)

    def layout_signals(self, left_id: str, right_id: str) -> LayoutSignals:
        key = self._symmetric_key(left_id, right_id)
        cached = self._layout_cache.get(key)
        if cached is not None:
            return cached
        left = self._span(left_id)
        right = self._span(right_id)
        left_page = left.page_ref.page_index if left.page_ref is not None else left.metadata.get("page_index")
        right_page = right.page_ref.page_index if right.page_ref is not None else right.metadata.get("page_index")
        try:
            left_page_int = int(left_page) if left_page is not None else None
            right_page_int = int(right_page) if right_page is not None else None
        except (TypeError, ValueError):
            left_page_int = None
            right_page_int = None
        same_page = bool(left_page_int is not None and right_page_int is not None and left_page_int == right_page_int)
        page_distance = abs(left_page_int - right_page_int) if left_page_int is not None and right_page_int is not None else None
        bbox_vertical_proximity = None
        if left.bbox is not None and right.bbox is not None and same_page:
            left_mid = (left.bbox.y0 + left.bbox.y1) / 2.0
            right_mid = (right.bbox.y0 + right.bbox.y1) / 2.0
            bbox_vertical_proximity = max(0.0, 1.0 - min(1.0, abs(left_mid - right_mid) / 1000.0))
        result = LayoutSignals(
            same_page=same_page,
            page_distance=page_distance,
            bbox_vertical_proximity=bbox_vertical_proximity,
            compatible=same_page or page_distance is None or page_distance <= 1,
        )
        self._layout_cache[key] = result
        return result

    def authority_signals(self, left_id: str, right_id: str) -> AuthoritySignals:
        key = self._symmetric_key(left_id, right_id)
        cached = self._authority_cache.get(key)
        if cached is not None:
            return cached
        left = self._span(left_id)
        right = self._span(right_id)
        same_author = bool(left.author_id and right.author_id and left.author_id == right.author_id)
        same_speaker = bool(left.speaker_id and right.speaker_id and left.speaker_id == right.speaker_id)
        same_actor_exact = same_author or same_speaker
        same_actor_alias = self._actor_alias_match(left, right)
        boundary_left = str(left.metadata.get("boundary_class", "")).strip().lower() or None
        boundary_right = str(right.metadata.get("boundary_class", "")).strip().lower() or None
        quoted_or_forwarded_mismatch = (
            {boundary_left, boundary_right} >= {"current_authored", "quoted_context"}
            or {boundary_left, boundary_right} >= {"current_authored", "forwarded_context"}
        )
        authority_delta = abs(float(left.authority_score) - float(right.authority_score))
        compatible = (same_actor_exact or same_actor_alias) and not quoted_or_forwarded_mismatch and authority_delta <= 0.35
        result = AuthoritySignals(
            same_author_id=same_author,
            same_speaker_id=same_speaker,
            same_actor_exact=same_actor_exact,
            same_actor_alias=same_actor_alias,
            boundary_class_left=boundary_left,
            boundary_class_right=boundary_right,
            authority_delta=authority_delta,
            quoted_or_forwarded_mismatch=quoted_or_forwarded_mismatch,
            compatible=compatible,
        )
        self._authority_cache[key] = result
        return result

    def chronology_signals(self, left_id: str, right_id: str) -> ChronologySignals:
        key = self._cache_key(left_id, right_id)
        cached = self._chronology_cache.get(key)
        if cached is not None:
            return cached
        left = self._span(left_id)
        right = self._span(right_id)
        left_rank = left.chronology_rank
        right_rank = right.chronology_rank
        both_ranked = left_rank is not None and right_rank is not None
        distance = abs(left_rank - right_rank) if both_ranked else None
        same_anchor = bool(left.time_anchor_id and right.time_anchor_id and left.time_anchor_id == right.time_anchor_id)
        explicit_pair = bool(left.time_anchor_id and right.time_anchor_id)
        temporal_order = bool(both_ranked and left_rank < right_rank)
        chronology_near = bool(distance is not None and distance <= 3)
        result = ChronologySignals(
            both_ranked=both_ranked,
            chronology_distance=distance,
            same_time_anchor=same_anchor,
            explicit_time_pair=explicit_pair,
            temporal_order=temporal_order,
            chronology_near=chronology_near,
        )
        self._chronology_cache[key] = result
        return result

    def cue_signals(self, left_id: str, right_id: str) -> CueSignals:
        key = self._symmetric_key(left_id, right_id)
        cached = self._cue_cache.get(key)
        if cached is not None:
            return cached
        left = self._span(left_id)
        right = self._span(right_id)
        left_cues = derive_span_cues(left)
        right_cues = derive_span_cues(right)
        left_set = set(left_cues)
        right_set = set(right_cues)
        shared = tuple(sorted(left_set & right_set))
        union_size = len(left_set | right_set)
        cue_similarity = (len(shared) / union_size) if union_size > 0 else 0.0
        lexical_cue_overlap = lexical_similarity(left, right)
        compatible = cue_similarity > 0.0 or lexical_cue_overlap >= 0.28
        result = CueSignals(
            left_cues=left_cues,
            right_cues=right_cues,
            cue_similarity=cue_similarity,
            shared_cues=shared,
            lexical_cue_overlap=lexical_cue_overlap,
            compatible=compatible,
        )
        self._cue_cache[key] = result
        return result

    def pair_signals(self, left_id: str, right_id: str) -> PairSignals:
        key = self._cache_key(left_id, right_id)
        cached = self._pair_cache.get(key)
        if cached is not None:
            return cached
        left = self._span(left_id)
        right = self._span(right_id)
        lexical = lexical_similarity(left, right)
        section_distance = self._section_distance(left, right)
        authority = self.authority_signals(left_id, right_id)
        chronology = self.chronology_signals(left_id, right_id)
        cue = self.cue_signals(left_id, right_id)
        ocr_compat, ocr_weak = self._ocr_compatibility(left, right)
        result = PairSignals(
            lexical_overlap=lexical,
            section_distance=section_distance,
            same_actor=authority.same_actor_exact or authority.same_actor_alias,
            same_message=bool(left.message_id and left.message_id == right.message_id),
            chronology_distance=chronology.chronology_distance,
            chronology_near=chronology.chronology_near,
            authority_compatible=authority.compatible,
            cue_similarity=cue.cue_similarity,
            ocr_confidence_compatibility=ocr_compat,
            ocr_weak_pair=ocr_weak,
        )
        self._pair_cache[key] = result
        return result

    # Backward-compatible helper methods used by passes.
    def span_distance(self, left: EvidenceSpan, right: EvidenceSpan) -> int:
        return span_position_distance(left, right)

    def same_section(self, left: EvidenceSpan, right: EvidenceSpan) -> bool:
        return tuple(left.section_path) == tuple(right.section_path)

    def same_message(self, left: EvidenceSpan, right: EvidenceSpan) -> bool:
        return bool(left.message_id and left.message_id == right.message_id)

    def quote_marker(self, span: EvidenceSpan) -> bool:
        return span_noise_hint(span)

    def temporal_order(self, left: EvidenceSpan, right: EvidenceSpan) -> bool:
        return self.chronology_signals(left.span_id, right.span_id).temporal_order

    def cue_values(self, span: EvidenceSpan) -> tuple[str, ...]:
        return derive_span_cues(span)

    def lexical_similarity(self, left: EvidenceSpan, right: EvidenceSpan) -> float:
        return lexical_similarity(left, right)

    def support_score(self, left: EvidenceSpan, right: EvidenceSpan) -> float:
        return support_score(left, right)

    def contradiction_score(self, left: EvidenceSpan, right: EvidenceSpan) -> float:
        return contradiction_score(left, right)

    def section_affinity(self, left: EvidenceSpan, right: EvidenceSpan) -> float:
        return section_affinity(left, right)
