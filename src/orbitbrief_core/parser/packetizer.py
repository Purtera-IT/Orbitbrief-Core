from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from orbitbrief_core.parser.packet_diagnostics import (
    PacketAnchorDiagnostic,
    PacketDebugBundle,
    PacketDiagnostic,
    PacketExclusionDiagnostic,
    PacketFamilyDiagnostic,
    PacketInclusionDiagnostic,
    PacketScoreContribution,
    build_packet_debug_bundle,
)
from orbitbrief_core.parser.packet_policies import get_packet_policy
from orbitbrief_core.parser.shared.types import AuthorityClass, DocumentParse, PacketCandidate, PacketKind

_PACKET_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scope_packet", ("scope", "included work", "in scope", "included", "main ask", "replace", "collect", "validate", "support")),
    ("exclusion_packet", ("exclude", "out of scope", "not included", "exclusion", "by others")),
    ("assumption_packet", ("assumption", "assume", "assuming", "unless", "will remain", "will be reused")),
    ("risk_packet", ("risk", "issue", "blocker", "possible issue", "delay", "older models", "escort required")),
    ("dependency_packet", ("dependency", "depends on", "approval", "access approvals", "third party", "vendor", "carrier")),
    ("site_packet", ("site", "sites", "location", "locations", "clinic", "branch", "hq", "idf", "mdf")),
    ("quantity_packet", ("qty", "quantity", "quantities", "count", "number of", "devices", "users", "printers", "aps", "switches", "conference rooms")),
    ("deliverable_packet", ("deliverable", "deliverables", "output", "handoff", "runbook", "report", "checklist", "worksheet", "log", "certificate", "matrix", "summary", "sop")),
    ("schedule_packet", ("schedule", "timeline", "date", "week", "month", "wave", "window", "after-hours", "go-live")),
    ("responsibility_packet", ("responsibility", "owner", "customer", "by others", "need from customer", "customer furnishes", "provide", "badge access", "escort", "release approvals")),
    ("open_question_packet", ("?", "open question", "open item", "unknown", "tbd", "confirm whether", "still need to confirm", "clarify")),
    ("drawing_metadata_packet", ("sheet number", "sheet title", "title block", "revision", "drawing", "plan")),
    ("site_identity_packet", ("site", "location", "address", "campus", "building", "floor")),
    ("network_room_or_closet_packet", ("mdf", "idf", "closet", "tr room", "telecom room")),
    ("equipment_reference_packet", ("ap-", "switch", "rack", "panel", "ups", "patch panel")),
    ("note_scope_packet", ("note", "general notes", "install note", "support note", "in scope", "out of scope")),
    ("revision_change_packet", ("rev ", "revision", "change")),
    ("topology_hint_packet", ("uplink", "trunk", "cross-connect", "neighbor", "patch")),
    ("constructability_packet", ("access", "badge", "escort", "loading dock", "after-hours", "constraint", "dependency", "readiness")),
    ("known_quantity_packet", ("qty", "quantity", "count", "x ", "ft", "sqft", "meters")),
)

_PACKET_TO_TARGET_CLAIMS: dict[str, tuple[str, ...]] = {
    "scope_packet": ("scope_included_claim",),
    "exclusion_packet": ("scope_excluded_claim",),
    "assumption_packet": ("assumption_claim",),
    "risk_packet": ("risk_claim",),
    "dependency_packet": ("third_party_dependency_claim",),
    "site_packet": ("site_location_claim",),
    "quantity_packet": ("known_quantity_claim",),
    "deliverable_packet": ("deliverable_claim",),
    "schedule_packet": ("schedule_claim",),
    "responsibility_packet": ("customer_responsibility_claim",),
    "open_question_packet": ("open_question_claim",),
    "drawing_metadata_packet": ("site_location_claim",),
    "site_identity_packet": ("site_location_claim",),
    "network_room_or_closet_packet": ("site_location_claim", "customer_responsibility_claim"),
    "equipment_reference_packet": ("known_quantity_claim", "third_party_dependency_claim"),
    "note_scope_packet": ("scope_included_claim", "scope_excluded_claim", "assumption_claim"),
    "revision_change_packet": ("deliverable_claim",),
    "topology_hint_packet": ("third_party_dependency_claim", "open_question_claim"),
    "constructability_packet": ("risk_claim", "third_party_dependency_claim", "customer_responsibility_claim"),
    "known_quantity_packet": ("known_quantity_claim",),
}

_CLAIM_TO_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "scope_included_claim": ("detailed_scope_of_services[]", "scope_included[]"),
    "scope_excluded_claim": ("out_of_scope[]", "scope_excluded[]"),
    "assumption_claim": ("assumptions[]",),
    "risk_claim": ("risks[]", "risks_or_dependencies[]"),
    "third_party_dependency_claim": ("third_party_dependencies[]", "risks_or_dependencies[]"),
    "site_location_claim": ("site_locations[]",),
    "site_count_claim": ("site_count",),
    "known_quantity_claim": ("scope_included[].quantity", "scope_included[].unit"),
    "deliverable_claim": ("deliverables[]", "deliverables_required[]"),
    "schedule_claim": ("completion_criteria[]",),
    "success_criteria": ("completion_criteria[]",),
    "customer_responsibility_claim": ("customer_responsibilities[]", "customer_inputs_required[]", "customer_documents_required[]", "customer_provided_materials[]"),
    "open_question_claim": ("open_questions[]", "open_items[]"),
    "access_logistics_claim": ("customer_responsibilities[]",),
    "drawing_metadata_claim": ("drawing_packet_metadata", "site_profile_from_drawings"),
}


@dataclass(frozen=True, slots=True)
class PacketizerResult:
    packets: tuple[PacketCandidate, ...]
    diagnostics: tuple[str, ...] = ()
    packet_debug_bundle: PacketDebugBundle | None = None


@dataclass(frozen=True, slots=True)
class AnchorCandidate:
    span_id: str
    score: float
    reason_codes: tuple[str, ...]
    family_hints: tuple[str, ...]


_CAD_MODALITIES = {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}
_CAD_NOISE_KINDS = {"legend", "table", "symbol_table", "boilerplate", "drawing_admin"}
_CAD_TITLE_BLOCK_KINDS = {"sheet_ref", "title_block", "title_block_field"}
_CAD_REVISION_KINDS = {"revision_block"}
_CAD_BODY_KINDS = {"note_block", "callout", "room_label", "equipment_label", "dimension_text", "visual_region"}
_CAD_EDGE_FAMILIES = {
    "same_sheet",
    "inside_zone",
    "inside_region",
    "near",
    "overlaps",
    "note_attached_to",
    "callout_for",
    "annotation_for",
    "component_in_zone",
    "component_near_component",
    "possible_topology_neighbor",
    "possible_support_area",
    "possible_distribution_room",
    "same_title_block",
    "same_revision_block",
    "sheet_metadata_for",
    "sheet_title_for",
    "revision_metadata_for",
    "revision_applies_to",
}
_CAD_SYMBOL_TOKEN_RE = re.compile(r"\b(?:AP|WAP|CCTV|RJ45|CAT6A?|SC|PATCH\s*PANEL|SWITCH)\b", flags=re.IGNORECASE)


def _kind(span) -> str:
    return str(span.metadata.get("kind", "")).strip().lower()


def _is_cad_noise(span) -> bool:
    if bool(span.metadata.get("cad_noise_downgraded")):
        return True
    kind = _kind(span)
    if kind in _CAD_NOISE_KINDS:
        return True
    text = span.normalized_text.lower()
    return any(token in text for token in ("legend", "symbol table", "boilerplate", "stamp"))


def _is_cad_anchor_eligible(span) -> bool:
    kind = _kind(span)
    if _is_cad_noise(span):
        return False
    if kind in _CAD_TITLE_BLOCK_KINDS | _CAD_REVISION_KINDS | _CAD_BODY_KINDS:
        return True
    return False


def _edge_ids_for_span_pairs(document_parse: DocumentParse) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    pair_to_edge_ids: dict[tuple[str, str], list[str]] = {}
    span_to_edge_ids: dict[str, list[str]] = {}
    for idx, edge in enumerate(document_parse.evidence_graph.edges):
        edge_id = f"edge:evidence:{idx:06d}:{edge.source_span_id}:{edge.target_span_id}:{edge.relation_type.value}"
        pair_to_edge_ids.setdefault((edge.source_span_id, edge.target_span_id), []).append(edge_id)
        pair_to_edge_ids.setdefault((edge.target_span_id, edge.source_span_id), []).append(edge_id)
        span_to_edge_ids.setdefault(edge.source_span_id, []).append(edge_id)
        span_to_edge_ids.setdefault(edge.target_span_id, []).append(edge_id)
    return pair_to_edge_ids, span_to_edge_ids


def _anchor_reason_codes(span) -> tuple[str, ...]:
    reasons: list[str] = []
    if float(span.metadata.get("packet_seed_score", 0.0) or 0.0) >= 0.54:
        reasons.append("packet_seed_edge")
    if span.authority_score >= 0.75:
        reasons.append("high_authority_span")
    if span.metadata.get("kind") in {"heading", "section_title"}:
        reasons.append("heading_seed")
    if span.cue_kinds:
        reasons.append("cue_seed")
    if not reasons:
        reasons.append("section_opener")
    return tuple(dict.fromkeys(reasons))


def _family_hints_for_span(span) -> tuple[str, ...]:
    hints: list[str] = []
    values = span.metadata.get("packet_families", ())
    if isinstance(values, (list, tuple)):
        for value in values:
            if value and str(value) not in hints:
                hints.append(str(value))
    parser_cues = span.metadata.get("parser_cues", ())
    if isinstance(parser_cues, (list, tuple)):
        for cue in parser_cues:
            cue_text = str(cue).lower()
            if "risk" in cue_text and "risk_packet" not in hints:
                hints.append("risk_packet")
            elif "assumption" in cue_text and "assumption_packet" not in hints:
                hints.append("assumption_packet")
            elif "deliverable" in cue_text and "deliverable_packet" not in hints:
                hints.append("deliverable_packet")
            elif "dependency" in cue_text and "dependency_packet" not in hints:
                hints.append("dependency_packet")
            elif "customer_responsibility" in cue_text and "responsibility_packet" not in hints:
                hints.append("responsibility_packet")
            elif "open_question" in cue_text and "open_question_packet" not in hints:
                hints.append("open_question_packet")
            elif cue_text in {"scope_included", "scope"} and "scope_packet" not in hints:
                hints.append("scope_packet")
            elif cue_text in {"scope_excluded", "scope_by_others"} and "exclusion_packet" not in hints:
                hints.append("exclusion_packet")
            elif cue_text in {"site_location", "site_count"} and "site_packet" not in hints:
                hints.append("site_packet")
            elif cue_text == "quantity" and "quantity_packet" not in hints:
                hints.append("quantity_packet")
            elif cue_text == "schedule" and "schedule_packet" not in hints:
                hints.append("schedule_packet")
    return tuple(hints)


def _family_competitors(blob: str, selected_family: str) -> tuple[str, ...]:
    competitors: list[str] = []
    text = blob.lower()
    for family_name, keywords in _PACKET_FAMILY_KEYWORDS:
        if family_name == selected_family:
            continue
        if any(keyword in text for keyword in keywords):
            competitors.append(family_name)
    return tuple(dict.fromkeys(competitors))


def _packet_target_claim_family_names(primary, family_name: str, competing_hints: tuple[str, ...], family_hints: tuple[str, ...]) -> tuple[str, ...]:
    names: list[str] = list(_PACKET_TO_TARGET_CLAIMS.get(family_name, ()))
    lower_blob = f"{primary.normalized_text.lower()} {' '.join(str(part).lower() for part in primary.section_path)}"
    parser_cues_raw = primary.metadata.get("parser_cues", ())
    parser_cues = {str(item).lower() for item in parser_cues_raw} if isinstance(parser_cues_raw, (list, tuple)) else set()

    for hint in (*family_hints, *competing_hints):
        if hint == family_name:
            continue
        for claim_name in _PACKET_TO_TARGET_CLAIMS.get(hint, ()): 
            if claim_name not in names:
                names.append(claim_name)
        if len(names) >= 4:
            break

    if (family_name in {"site_packet", "quantity_packet"} or "site_count" in parser_cues or "sites are around" in lower_blob) and any(token in lower_blob for token in ("site count", "sites", "locations", "offices", "clinics", "branches")):
        if "site_count_claim" not in names:
            names.append("site_count_claim")
    if any(token in lower_blob for token in ("possible issue", "key risk", "risk:", "risk ")):
        if "risk_claim" not in names:
            names.append("risk_claim")
    if any(token in lower_blob for token in ("still need to confirm", "confirm whether", "not sure", "unknown", "tbd")):
        if "open_question_claim" not in names:
            names.append("open_question_claim")
    if any(token in lower_blob for token in ("deliverable", "draft deliverable", "runbook", "support matrix", "handoff process", "chain-of-custody log", "ap placement markup")):
        if "deliverable_claim" not in names:
            names.append("deliverable_claim")
    if any(token in lower_blob for token in ("main ask", "first ask heard", "included work", "in scope")):
        if "scope_included_claim" not in names:
            names.append("scope_included_claim")
    if family_name == "risk_packet" and any(token in lower_blob for token in ("badge", "escort", "background check", "ppe", "after-hours", "access")):
        if "access_logistics_claim" not in names:
            names.append("access_logistics_claim")
    if family_name in {"schedule_packet", "deliverable_packet"} and any(token in lower_blob for token in ("done looks like", "completion criteria", "accepted", "validated", "fully onboarded")):
        if "success_criteria" not in names:
            names.append("success_criteria")
    return tuple(dict.fromkeys(names))


def _packet_target_field_paths(target_claim_family_names: tuple[str, ...]) -> tuple[str, ...]:
    paths: list[str] = []
    for claim_name in target_claim_family_names:
        for path in _CLAIM_TO_FIELD_PATHS.get(claim_name, ()): 
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def _section_distance(anchor_path: tuple[str, ...], span_path: tuple[str, ...]) -> int:
    common = 0
    for left, right in zip(anchor_path, span_path):
        if left != right:
            break
        common += 1
    return (len(anchor_path) - common) + (len(span_path) - common)


def _is_quoted_or_forwarded(span) -> tuple[bool, bool]:
    boundary_class = str(span.metadata.get("boundary_class", "")).lower()
    return (boundary_class == "quoted_context", boundary_class == "forwarded_context")


def _classify_family(anchor, supports, keywords_by_family: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[str, tuple[str, ...], float, tuple[str, ...]]:
    aggregate = " ".join([anchor.normalized_text, " ".join(anchor.section_path)] + [span.normalized_text for span in supports]).lower()
    scores: dict[str, float] = {}
    for family_name, keywords in keywords_by_family:
        lexical_hits = sum(1 for keyword in keywords if keyword in aggregate)
        cue_hits = 0
        for cue in anchor.cue_kinds:
            cue_text = str(getattr(cue, "value", cue)).lower()
            if "risk" in cue_text and family_name == "risk_packet":
                cue_hits += 2
            elif "schedule" in cue_text and family_name == "schedule_packet":
                cue_hits += 2
            elif "quantity" in cue_text and family_name == "quantity_packet":
                cue_hits += 2
            elif "uncertainty" in cue_text and family_name == "open_question_packet":
                cue_hits += 2
            elif "negation" in cue_text and family_name == "exclusion_packet":
                cue_hits += 1
            elif "commitment" in cue_text and family_name in {"deliverable_packet", "scope_packet", "responsibility_packet"}:
                cue_hits += 1
        heading_bonus = 1.5 if family_name.startswith("risk") and any("risk" in str(path).lower() for path in anchor.section_path) else 0.0
        scores[family_name] = (lexical_hits * 1.0) + (cue_hits * 0.9) + heading_bonus + (anchor.authority_score * 0.35)

    sorted_families = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    selected_family, selected_score = sorted_families[0]
    competing = tuple(name for name, score in sorted_families[1:3] if score > 0.0)
    total = sum(max(0.0, value) for value in scores.values()) or 1.0
    confidence = max(0.2, min(0.95, selected_score / total + 0.25))
    rationale_codes = ["anchor_family_hint", "support_cue_alignment"]
    if any(selected_family.split("_")[0] in path.lower() for path in anchor.section_path):
        rationale_codes.append("section_label_alignment")
    if "deliverable" in aggregate and selected_family == "deliverable_packet":
        rationale_codes.append("heading_label_alignment")
    return selected_family, tuple(dict.fromkeys(rationale_codes)), confidence, competing


def _generate_anchor_candidates(spans) -> tuple[AnchorCandidate, ...]:
    candidates: list[AnchorCandidate] = []
    for span in spans:
        reason_codes: list[str] = []
        family_hints = _family_hints_for_span(span)
        score = 0.0
        seed_score = float(span.metadata.get("packet_seed_score", 0.0) or 0.0)
        if seed_score >= 0.54:
            score += min(0.32, seed_score * 0.4)
            reason_codes.append("packet_seed_edge")
        if span.metadata.get("kind") in {"heading", "section_title"}:
            score += 0.15
            reason_codes.append("heading_seed")
        if span.cue_kinds:
            score += min(0.2, len(span.cue_kinds) * 0.08)
            reason_codes.append("cue_seed")
        target_claim_hints = span.metadata.get("target_claim_family_hints", ())
        if isinstance(target_claim_hints, (list, tuple)) and any(str(item).strip() for item in target_claim_hints):
            score += 0.18
            reason_codes.append("semantic_hint_seed")
        text = span.normalized_text.lower()
        if any(keyword in text for _, keywords in _PACKET_FAMILY_KEYWORDS for keyword in keywords):
            score += 0.12
            reason_codes.append("lexical_seed")
        if span.authority_score >= 0.75:
            score += 0.22
            reason_codes.append("high_authority_span")
        boundary_class = str(span.metadata.get("boundary_class", "")).lower()
        if boundary_class == "current_authored":
            score += 0.15
        if boundary_class in {"quoted_context", "forwarded_context", "signature", "disclaimer"}:
            score -= 0.2
        ocr_conf = span.metadata.get("ocr_confidence")
        try:
            if ocr_conf is not None and float(ocr_conf) < 0.45:
                score -= 0.08
        except (TypeError, ValueError):
            pass
        if score < 0.38:
            continue
        if not reason_codes:
            reason_codes.append("section_opener")
        candidates.append(
            AnchorCandidate(
                span_id=span.span_id,
                score=round(max(0.0, min(1.0, score)), 6),
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                family_hints=family_hints,
            )
        )
    if not candidates and spans:
        fallback = sorted(spans, key=lambda span: (span.authority_score, span.span_id), reverse=True)[:2]
        for span in fallback:
            candidates.append(
                AnchorCandidate(
                    span_id=span.span_id,
                    score=round(max(0.0, min(1.0, span.authority_score * 0.75)), 6),
                    reason_codes=("fallback_authority_anchor",),
                    family_hints=_family_hints_for_span(span),
                )
            )
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.span_id)))


def _edge_maps(document_parse: DocumentParse) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]], dict[str, str]]:
    pair_to_edge_ids: dict[tuple[str, str], list[str]] = {}
    span_to_edge_ids: dict[str, list[str]] = {}
    edge_family_by_id: dict[str, str] = {}
    for idx, edge in enumerate(document_parse.evidence_graph.edges):
        edge_id = f"edge:evidence:{idx:06d}:{edge.source_span_id}:{edge.target_span_id}:{edge.relation_type.value}"
        family = str(edge.metadata.get("edge_family", ""))
        edge_family_by_id[edge_id] = family
        pair_to_edge_ids.setdefault((edge.source_span_id, edge.target_span_id), []).append(edge_id)
        pair_to_edge_ids.setdefault((edge.target_span_id, edge.source_span_id), []).append(edge_id)
        span_to_edge_ids.setdefault(edge.source_span_id, []).append(edge_id)
        span_to_edge_ids.setdefault(edge.target_span_id, []).append(edge_id)
    return pair_to_edge_ids, span_to_edge_ids, edge_family_by_id


def _same_sheet(anchor, candidate) -> bool:
    return tuple(anchor.section_path[:2]) == tuple(candidate.section_path[:2]) and len(anchor.section_path) >= 2 and len(candidate.section_path) >= 2


def _page_index(span) -> int | None:
    raw = span.metadata.get("page_index")
    if isinstance(raw, int):
        return raw
    return None


def _has_binding_edges(
    source_span_id: str,
    target_span_id: str,
    *,
    pair_to_edge_ids: Mapping[tuple[str, str], list[str]],
    edge_family_by_id: Mapping[str, str],
) -> bool:
    families = {
        edge_family_by_id.get(edge_id, "")
        for edge_id in (
            pair_to_edge_ids.get((source_span_id, target_span_id), [])
            + pair_to_edge_ids.get((target_span_id, source_span_id), [])
        )
    }
    return bool(
        families.intersection(
            {
                "callout_for",
                "note_attached_to",
                "annotation_for",
                "component_in_zone",
                "inside_zone",
                "inside_region",
                "possible_topology_neighbor",
            }
        )
    )


def _symbol_tokens(spans: list[Any]) -> set[str]:
    out: set[str] = set()
    for span in spans:
        kind = _kind(span)
        if kind not in {"legend", "symbol_table", "note_block"}:
            continue
        text = span.normalized_text
        if "symbol" not in text and kind != "symbol_table":
            continue
        for match in _CAD_SYMBOL_TOKEN_RE.finditer(text):
            out.add(match.group(0).lower())
    return out


def _cad_anchor_candidates(spans) -> tuple[AnchorCandidate, ...]:
    score_by_kind = {
        "sheet_ref": 0.84,
        "title_block": 0.8,
        "title_block_field": 0.82,
        "revision_block": 0.75,
        "note_block": 0.72,
        "callout": 0.68,
        "room_label": 0.82,
        "equipment_label": 0.76,
        "dimension_text": 0.62,
        "visual_region": 0.52,
    }
    out: list[AnchorCandidate] = []
    symbols = _symbol_tokens(list(spans))
    for span in spans:
        if not _is_cad_anchor_eligible(span):
            continue
        kind = _kind(span)
        score = score_by_kind.get(kind, 0.45) + (span.authority_score * 0.22)
        reason_codes: list[str] = [f"anchor_kind_{kind or 'unknown'}"]
        family_hints = list(_family_hints_for_span(span))
        if family_hints:
            score += 0.08
            reason_codes.append("packet_family_hint")
        if kind in _CAD_TITLE_BLOCK_KINDS:
            reason_codes.append("title_block_anchor")
        if kind in {"room_label", "equipment_label"}:
            reason_codes.append("drawing_body_anchor")
        if kind == "equipment_label" and symbols and any(token in span.normalized_text.lower() for token in symbols):
            score += 0.12
            reason_codes.append("symbol_dictionary_alignment")
        if kind == "note_block":
            reason_codes.append("annotation_anchor")
        if kind in _CAD_REVISION_KINDS:
            reason_codes.append("revision_anchor")
        ocr_confidence = span.metadata.get("ocr_confidence")
        try:
            if ocr_confidence is not None and float(ocr_confidence) < 0.45:
                score -= 0.12
                reason_codes.append("weak_ocr_penalty")
        except (TypeError, ValueError):
            pass
        if span.authority_score < 0.45:
            score -= 0.08
        if score < 0.46:
            continue
        out.append(
            AnchorCandidate(
                span_id=span.span_id,
                score=round(max(0.0, min(1.0, score)), 6),
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                family_hints=tuple(dict.fromkeys(family_hints)),
            )
        )
    return tuple(sorted(out, key=lambda item: (-item.score, item.span_id)))


def _cad_family_from_context(anchor, included, edge_families: list[str], family_hints: tuple[str, ...]) -> tuple[str, tuple[str, ...], float, tuple[str, ...]]:
    kind = _kind(anchor)
    text = anchor.normalized_text.lower()
    family_scores: dict[str, float] = {}
    for family in (
        "drawing_metadata_packet",
        "site_identity_packet",
        "network_room_or_closet_packet",
        "equipment_reference_packet",
        "note_scope_packet",
        "revision_change_packet",
        "topology_hint_packet",
        "constructability_packet",
    ):
        family_scores[family] = 0.0
    for hint in family_hints:
        if hint in family_scores:
            family_scores[hint] += 0.7
    if kind in _CAD_TITLE_BLOCK_KINDS:
        family_scores["drawing_metadata_packet"] += 1.2
        family_scores["site_identity_packet"] += 0.4
    if kind in _CAD_REVISION_KINDS:
        family_scores["revision_change_packet"] += 1.2
    if kind == "room_label":
        family_scores["network_room_or_closet_packet"] += 1.0
        family_scores["site_identity_packet"] += 0.35
    if kind == "equipment_label":
        family_scores["equipment_reference_packet"] += 1.0
        family_scores["topology_hint_packet"] += 0.35
    if kind in {"note_block", "callout"}:
        family_scores["note_scope_packet"] += 0.9
        family_scores["constructability_packet"] += 0.45
    if any(token in text for token in ("mdf", "idf", "closet", "telecom room")):
        family_scores["network_room_or_closet_packet"] += 0.75
    if any(token in text for token in ("access", "badge", "escort", "after-hours", "constraint", "readiness")):
        family_scores["constructability_packet"] += 0.75
    if any(token in text for token in ("rev ", "revision", "change")):
        family_scores["revision_change_packet"] += 0.7
    if "title" in text or "sheet number" in text:
        family_scores["drawing_metadata_packet"] += 0.75

    for family in edge_families:
        if family in {"same_title_block", "sheet_metadata_for", "sheet_title_for"} and kind in _CAD_TITLE_BLOCK_KINDS:
            family_scores["drawing_metadata_packet"] += 0.45
        if family in {"same_revision_block", "revision_metadata_for", "revision_applies_to"} and kind in _CAD_REVISION_KINDS:
            family_scores["revision_change_packet"] += 0.45
        if family in {"component_in_zone", "inside_zone", "possible_distribution_room"}:
            family_scores["network_room_or_closet_packet"] += 0.35
        if family in {"component_near_component", "possible_topology_neighbor"}:
            family_scores["topology_hint_packet"] += 0.4
            family_scores["equipment_reference_packet"] += 0.2
        if family in {"note_attached_to", "annotation_for", "callout_for"}:
            family_scores["note_scope_packet"] += 0.35
            family_scores["constructability_packet"] += 0.2

    # slight support-size prior
    family_scores["site_identity_packet"] += min(0.25, len(included) * 0.03)
    ranked = sorted(family_scores.items(), key=lambda item: (-item[1], item[0]))
    selected_family, selected_score = ranked[0]
    competitors = tuple(name for name, score in ranked[1:3] if score >= 0.3)
    total = sum(max(0.0, value) for value in family_scores.values()) or 1.0
    family_conf = max(0.3, min(0.96, selected_score / total + 0.28))
    rationale = ["cad_anchor_kind_match", "cad_graph_edge_alignment"]
    if family_hints:
        rationale.append("cad_family_hint_alignment")
    return selected_family, tuple(dict.fromkeys(rationale)), round(family_conf, 6), competitors


def _build_cad_packets(
    document_parse: DocumentParse,
    *,
    spans: list[Any],
    span_by_id: Mapping[str, Any],
) -> PacketizerResult:
    diagnostics: list[str] = []
    packets: list[PacketCandidate] = []
    packet_diagnostics: list[PacketDiagnostic] = []
    pair_to_edge_ids, span_to_edge_ids, edge_family_by_id = _edge_maps(document_parse)
    anchor_candidates = _cad_anchor_candidates(spans)
    anchor_candidates = anchor_candidates[:14]
    consumed_anchor_ids: set[str] = set()
    packet_index = 0
    metadata = dict(document_parse.metadata)

    # Build cluster lookup tables from strategy enrichment.
    cluster_index: dict[str, set[str]] = {}
    for cluster in metadata.get("note_clusters", []):
        if not isinstance(cluster, Mapping):
            continue
        ids = {str(item.get("span_id")) for item in cluster.get("items", []) if isinstance(item, Mapping) and item.get("span_id")}
        for item in ids:
            cluster_index[item] = ids
    for cluster in metadata.get("revision_bundle", []):
        if not isinstance(cluster, Mapping):
            continue
        ids = {str(item.get("span_id")) for item in cluster.get("entries", []) if isinstance(item, Mapping) and item.get("span_id")}
        for item in ids:
            cluster_index[item] = cluster_index.get(item, set()) | ids
    for cluster in metadata.get("title_block_bundle", []):
        if not isinstance(cluster, Mapping):
            continue
        ids = {str(item.get("span_id")) for item in cluster.get("fields", []) if isinstance(item, Mapping) and item.get("span_id")}
        for item in ids:
            cluster_index[item] = cluster_index.get(item, set()) | ids

    for anchor in anchor_candidates:
        if anchor.span_id in consumed_anchor_ids:
            continue
        primary = span_by_id.get(anchor.span_id)
        if primary is None:
            continue
        family_policy_family = anchor.family_hints[0] if anchor.family_hints else "drawing_metadata_packet"
        policy = get_packet_policy(family_policy_family)
        if anchor.score < policy.min_anchor_score:
            continue

        # Graph-backed neighborhood expansion with CAD edge families + strategy clusters.
        ring_neighbors: set[str] = {primary.span_id}
        for pair, edge_ids in pair_to_edge_ids.items():
            if pair[0] != primary.span_id:
                continue
            allowed = [edge_id for edge_id in edge_ids if edge_family_by_id.get(edge_id, "") in _CAD_EDGE_FAMILIES]
            if allowed:
                ring_neighbors.add(pair[1])
        ring_neighbors.update(cluster_index.get(primary.span_id, set()))

        support_candidates = [span_by_id[span_id] for span_id in ring_neighbors if span_id in span_by_id]
        support_candidates = [span for span in support_candidates if span is not None]
        support_candidates = sorted({span.span_id: span for span in support_candidates}.values(), key=lambda span: span.span_id)

        included_spans: list[Any] = []
        excluded_spans: list[tuple[Any, tuple[str, ...]]] = []
        noise_suppressed = 0
        attachment_scores: list[float] = []
        for candidate in support_candidates:
            if candidate.span_id == primary.span_id:
                included_spans.append(candidate)
                continue
            reasons: list[str] = []
            candidate_kind = _kind(candidate)
            primary_kind = _kind(primary)
            if _is_cad_noise(candidate):
                reasons.append("noise_region_suppressed")
                noise_suppressed += 1
            if not _same_sheet(primary, candidate):
                reasons.append("unrelated_sheet")
            # Keep title block and revision neighborhoods bounded unless explicit linking edge exists.
            connecting_families = {
                edge_family_by_id.get(edge_id, "")
                for edge_id in (
                    pair_to_edge_ids.get((primary.span_id, candidate.span_id), [])
                    + pair_to_edge_ids.get((candidate.span_id, primary.span_id), [])
                )
            }
            if primary_kind in _CAD_TITLE_BLOCK_KINDS and candidate_kind in _CAD_BODY_KINDS:
                if not connecting_families.intersection({"sheet_metadata_for", "sheet_title_for"}):
                    reasons.append("title_block_boundary")
            if primary_kind in _CAD_REVISION_KINDS and candidate_kind in _CAD_BODY_KINDS:
                if not connecting_families.intersection({"revision_metadata_for", "revision_applies_to", "same_revision_block"}):
                    reasons.append("revision_boundary")
            if candidate.authority_score < policy.min_support_authority:
                reasons.append("low_authority")
            if candidate.metadata.get("ocr_confidence") is not None:
                try:
                    if float(candidate.metadata.get("ocr_confidence")) < 0.45:
                        reasons.append("weak_ocr")
                except (TypeError, ValueError):
                    pass
            if reasons:
                excluded_spans.append((candidate, tuple(dict.fromkeys(reasons))))
                continue
            included_spans.append(candidate)
            if connecting_families.intersection({"note_attached_to", "callout_for", "annotation_for", "component_in_zone"}):
                attachment_scores.append(0.72)
            elif connecting_families.intersection({"near", "inside_zone", "inside_region"}):
                attachment_scores.append(0.62)
            else:
                attachment_scores.append(0.5)

        included_spans = included_spans[: policy.max_support_spans]
        if not included_spans:
            continue

        edge_ids = set()
        edge_families_for_packet: list[str] = []
        for span in included_spans:
            direct_ids = (
                pair_to_edge_ids.get((primary.span_id, span.span_id), [])
                + pair_to_edge_ids.get((span.span_id, primary.span_id), [])
            )
            for edge_id in direct_ids:
                edge_ids.add(edge_id)
                fam = edge_family_by_id.get(edge_id, "")
                if fam:
                    edge_families_for_packet.append(fam)
            for edge_id in span_to_edge_ids.get(span.span_id, []):
                edge_ids.add(edge_id)

        family_name, family_rationale_codes, family_confidence, competing_hints = _cad_family_from_context(
            primary,
            included_spans,
            edge_families_for_packet,
            anchor.family_hints,
        )

        # Family-specific locality pruning: keep packets page/region-local unless explicitly bound.
        primary_page = _page_index(primary)
        pruned: list[tuple[Any, tuple[str, ...]]] = []
        locality_sensitive = family_name in {
            "network_room_or_closet_packet",
            "equipment_reference_packet",
            "constructability_packet",
            "note_scope_packet",
            "topology_hint_packet",
        }
        if locality_sensitive:
            filtered: list[Any] = []
            for span in included_spans:
                if span.span_id == primary.span_id:
                    filtered.append(span)
                    continue
                reasons: list[str] = []
                span_page = _page_index(span)
                if primary_page is not None and span_page is not None and span_page != primary_page:
                    if not _has_binding_edges(
                        primary.span_id,
                        span.span_id,
                        pair_to_edge_ids=pair_to_edge_ids,
                        edge_family_by_id=edge_family_by_id,
                    ):
                        reasons.append("page_local_boundary")
                span_kind = _kind(span)
                if family_name in {"network_room_or_closet_packet", "equipment_reference_packet"}:
                    if span_kind in {"title_block", "title_block_field", "sheet_ref", "revision_block"}:
                        reasons.append("metadata_boundary")
                    if span_kind == "note_block" and not _has_binding_edges(
                        primary.span_id,
                        span.span_id,
                        pair_to_edge_ids=pair_to_edge_ids,
                        edge_family_by_id=edge_family_by_id,
                    ):
                        reasons.append("unrelated_note_context")
                if reasons:
                    pruned.append((span, tuple(dict.fromkeys(reasons))))
                    continue
                filtered.append(span)
            included_spans = filtered or [primary]

        if pruned:
            excluded_spans.extend(pruned)

        policy = get_packet_policy(family_name)
        included_spans = included_spans[: policy.max_support_spans]
        span_ids = tuple(sorted(span.span_id for span in included_spans))
        avg_authority = sum(span.authority_score for span in included_spans) / max(1, len(included_spans))
        same_sheet_ratio = (
            sum(1 for span in included_spans if _same_sheet(primary, span)) / max(1, len(included_spans))
        )
        geometry_cohesion = min(1.0, (sum(attachment_scores) / max(1, len(attachment_scores)))) if attachment_scores else 0.45
        noise_risk = min(1.0, noise_suppressed / max(1, len(support_candidates)))
        confidence = max(
            0.25,
            min(
                0.96,
                (anchor.score * 0.3)
                + (avg_authority * 0.28)
                + (same_sheet_ratio * 0.15)
                + (geometry_cohesion * 0.14)
                + (family_confidence * 0.2)
                - (noise_risk * 0.18),
            ),
        )
        review_reasons: list[str] = []
        if confidence < 0.66:
            review_reasons.append("low_packet_confidence")
        if any(flag.severity.value == "high" for flag in document_parse.review_flags):
            review_reasons.append("source_high_review_flag")
        if noise_suppressed > 0:
            review_reasons.append("noise_contamination_risk")
        if avg_authority < 0.55:
            review_reasons.append("low_support_authority")
        packet_state = "extract"
        if confidence < 0.48:
            packet_state = "parked"
        elif review_reasons:
            packet_state = "review_required"

        packet_id = f"packet:{family_name}:{packet_index:04d}"
        packet_index += 1
        consumed_anchor_ids.add(primary.span_id)
        anchor_diag = PacketAnchorDiagnostic(
            anchor_span_id=primary.span_id,
            reason_codes=anchor.reason_codes,
            family_hints=tuple(dict.fromkeys(anchor.family_hints)),
            authority_class=primary.authority_class.value,
            confidence=round(anchor.score, 6),
        )
        included_diag: list[PacketInclusionDiagnostic] = []
        for span in included_spans:
            connecting_edges = tuple(
                dict.fromkeys(
                    pair_to_edge_ids.get((primary.span_id, span.span_id), [])
                    + pair_to_edge_ids.get((span.span_id, primary.span_id), [])
                )
            )
            reasons = ["same_sheet_context"] if _same_sheet(primary, span) else ["cross_sheet_context"]
            if span.span_id == primary.span_id:
                reasons = ["cad_anchor"]
            if any(edge_family_by_id.get(edge_id, "") in {"callout_for", "note_attached_to", "annotation_for"} for edge_id in connecting_edges):
                reasons.append("attachment_edge")
            if any(edge_family_by_id.get(edge_id, "") in {"inside_zone", "component_in_zone", "possible_distribution_room"} for edge_id in connecting_edges):
                reasons.append("zone_edge")
            role = "direct_support" if span.span_id == primary.span_id else "section_context"
            included_diag.append(
                PacketInclusionDiagnostic(
                    span_id=span.span_id,
                    inclusion_reason_codes=tuple(dict.fromkeys(reasons)),
                    graph_edges_used=connecting_edges,
                    authority_class=span.authority_class.value,
                    confidence=round(span.authority_score, 6),
                    role=role,
                )
            )
        excluded_diag: list[PacketExclusionDiagnostic] = []
        for span, reasons in excluded_spans:
            candidate_edges = tuple(
                dict.fromkeys(
                    pair_to_edge_ids.get((primary.span_id, span.span_id), [])
                    + pair_to_edge_ids.get((span.span_id, primary.span_id), [])
                    + span_to_edge_ids.get(span.span_id, [])
                )
            )
            excluded_diag.append(
                PacketExclusionDiagnostic(
                    span_id=span.span_id,
                    exclusion_reason_codes=reasons,
                    graph_edges_considered=candidate_edges,
                )
            )
        score_contributions = (
            PacketScoreContribution("anchor_strength", round(anchor.score, 6), ("cad_anchor",)),
            PacketScoreContribution("support_quality", round(avg_authority, 6), ("authority_support",)),
            PacketScoreContribution("geometry_coherence", round(geometry_cohesion, 6), ("cad_geometry_signal",)),
            PacketScoreContribution("family_score", round(family_confidence, 6), ("cad_family_fit",)),
            PacketScoreContribution("noise_contamination_penalty", round(-noise_risk, 6), ("noise_region_suppressed",)),
        )
        family_diag = PacketFamilyDiagnostic(
            assigned_family=family_name,
            rationale_codes=family_rationale_codes,
            competing_family_hints=competing_hints,
            family_confidence=round(family_confidence, 6),
        )
        uncertainty_markers: list[str] = []
        if noise_suppressed > 0:
            uncertainty_markers.append("noise_regions_suppressed")
        if confidence < 0.6:
            uncertainty_markers.append("weak_anchor")
        if avg_authority < 0.55:
            uncertainty_markers.append("low_authority_support")
        if packet_state != "extract":
            uncertainty_markers.append(packet_state)
        if competing_hints:
            uncertainty_markers.append("family_conflict")
        packet_diag = PacketDiagnostic(
            packet_id=packet_id,
            anchor=anchor_diag,
            included=tuple(included_diag),
            excluded=tuple(excluded_diag),
            family=family_diag,
            score_contributions=score_contributions,
            graph_edges_used=tuple(sorted(edge_ids)),
            uncertainty_markers=tuple(dict.fromkeys(uncertainty_markers)),
        )
        packet_diagnostics.append(packet_diag)
        target_claim_family_names = _packet_target_claim_family_names(primary, family_name, competing_hints, anchor.family_hints)
        target_field_paths = _packet_target_field_paths(target_claim_family_names)
        packets.append(
            PacketCandidate(
                packet_id=packet_id,
                packet_kind=PacketKind.CLAIM,
                span_ids=span_ids,
                primary_span_id=primary.span_id,
                target_field_paths=target_field_paths,
                target_claim_family_names=target_claim_family_names,
                confidence=round(confidence, 6),
                authority_class=AuthorityClass.FIRST_PASS if confidence >= 0.62 else AuthorityClass.UNKNOWN,
                metadata={
                    "packet_family": family_name,
                    "packet_policy": document_parse.metadata.get("adapter_context", {}).get("packet_policy"),
                    "packet_state": packet_state,
                    "span_count": len(span_ids),
                    "packet_diagnostic": packet_diag.to_dict(),
                    "graph_edges_used": list(packet_diag.graph_edges_used),
                    "uncertainty_markers": list(packet_diag.uncertainty_markers),
                    "cad_packetizer": {
                        "anchor_kind": _kind(primary),
                        "anchor_confidence": round(anchor.score, 6),
                        "family_score": round(family_confidence, 6),
                        "edge_count": len(edge_ids),
                        "noise_regions_suppressed": noise_suppressed,
                        "attachment_confidence": round(sum(attachment_scores) / max(1, len(attachment_scores)), 6) if attachment_scores else 0.0,
                        "review_reasons": review_reasons,
                    },
                },
            )
        )
        diagnostics.append(
            f"packetized_cad:{family_name}:{len(span_ids)}:state={packet_state}:suppressed_noise={noise_suppressed}"
        )

    if not packets and spans:
        # Fail-closed fallback for weak CAD sheets: park the strongest non-noise span.
        fallback_candidates = [span for span in spans if not _is_cad_noise(span)]
        if not fallback_candidates:
            fallback_candidates = list(spans)
        if fallback_candidates:
            primary = sorted(fallback_candidates, key=lambda span: (span.authority_score, span.span_id), reverse=True)[0]
            packet_id = "packet:cad_fallback:0000"
            anchor_diag = PacketAnchorDiagnostic(
                anchor_span_id=primary.span_id,
                reason_codes=("cad_fallback_anchor",),
                family_hints=_family_hints_for_span(primary),
                authority_class=primary.authority_class.value,
                confidence=round(primary.authority_score, 6),
            )
            family_diag = PacketFamilyDiagnostic(
                assigned_family="drawing_metadata_packet",
                rationale_codes=("cad_fallback_classification",),
                competing_family_hints=(),
                family_confidence=0.35,
            )
            packet_diag = PacketDiagnostic(
                packet_id=packet_id,
                anchor=anchor_diag,
                included=(
                    PacketInclusionDiagnostic(
                        span_id=primary.span_id,
                        inclusion_reason_codes=("cad_fallback_anchor",),
                        graph_edges_used=(),
                        authority_class=primary.authority_class.value,
                        confidence=round(primary.authority_score, 6),
                        role="direct_support",
                    ),
                ),
                excluded=(),
                family=family_diag,
                score_contributions=(PacketScoreContribution("anchor_strength", round(primary.authority_score, 6), ("cad_fallback_anchor",)),),
                graph_edges_used=(),
                uncertainty_markers=("parked", "cad_fallback_packet"),
            )
            packet_diagnostics.append(packet_diag)
            target_claim_family_names = _packet_target_claim_family_names(primary, "drawing_metadata_packet", (), _family_hints_for_span(primary))
            packets.append(
                PacketCandidate(
                    packet_id=packet_id,
                    packet_kind=PacketKind.CLAIM,
                    span_ids=(primary.span_id,),
                    primary_span_id=primary.span_id,
                    target_field_paths=_packet_target_field_paths(target_claim_family_names),
                    target_claim_family_names=target_claim_family_names,
                    confidence=max(0.25, min(0.5, primary.authority_score)),
                    authority_class=AuthorityClass.UNKNOWN,
                    metadata={
                        "packet_family": "drawing_metadata_packet",
                        "packet_state": "parked",
                        "span_count": 1,
                        "packet_diagnostic": packet_diag.to_dict(),
                        "graph_edges_used": [],
                        "uncertainty_markers": list(packet_diag.uncertainty_markers),
                        "cad_packetizer": {
                            "anchor_kind": _kind(primary),
                            "anchor_confidence": round(primary.authority_score, 6),
                            "family_score": 0.35,
                            "edge_count": 0,
                            "noise_regions_suppressed": 0,
                            "attachment_confidence": 0.0,
                            "review_reasons": ["cad_fallback_packet"],
                        },
                    },
                )
            )
            diagnostics.append("packetized_cad_fallback:parked")

    debug_bundle = build_packet_debug_bundle(packet_diagnostics)
    return PacketizerResult(
        packets=tuple(sorted(packets, key=lambda packet: packet.packet_id)),
        diagnostics=tuple(diagnostics),
        packet_debug_bundle=debug_bundle,
    )


def build_packets(document_parse: DocumentParse, *, compiled_pack: Any | None = None) -> PacketizerResult:
    diagnostics: list[str] = []
    spans = list(document_parse.evidence_spans)
    span_by_id = {span.span_id: span for span in spans}
    if document_parse.modality in _CAD_MODALITIES:
        return _build_cad_packets(document_parse, spans=spans, span_by_id=span_by_id)
    packets: list[PacketCandidate] = []
    packet_diagnostics: list[PacketDiagnostic] = []
    pair_to_edge_ids, span_to_edge_ids = _edge_ids_for_span_pairs(document_parse)
    ordered_ids = [span.span_id for span in spans]
    packet_index = 0
    anchor_candidates = _generate_anchor_candidates(spans)
    consumed_anchor_ids: set[str] = set()
    for anchor in anchor_candidates:
        if anchor.span_id in consumed_anchor_ids:
            continue
        primary = span_by_id[anchor.span_id]
        if primary is None:
            continue
        direct_neighbors = {
            neighbor_id
            for pair, edge_ids in pair_to_edge_ids.items()
            if pair[0] == primary.span_id and edge_ids
            for neighbor_id in [pair[1]]
        }
        # bounded ring expansion with adjacency and graph support
        try:
            anchor_pos = ordered_ids.index(primary.span_id)
        except ValueError:
            anchor_pos = -1
        ring_neighbors: set[str] = set(direct_neighbors)
        if anchor_pos >= 0:
            for offset in (-2, -1, 1, 2):
                idx = anchor_pos + offset
                if 0 <= idx < len(ordered_ids):
                    ring_neighbors.add(ordered_ids[idx])
        support_candidates = [span_by_id[span_id] for span_id in ring_neighbors if span_id in span_by_id]
        support_candidates = [span for span in support_candidates if span is not None]
        support_candidates.append(primary)
        support_candidates = sorted({span.span_id: span for span in support_candidates}.values(), key=lambda span: span.span_id)

        family_name, family_rationale_codes, family_confidence, competing_hints = _classify_family(primary, support_candidates, _PACKET_FAMILY_KEYWORDS)
        family_keywords = dict(_PACKET_FAMILY_KEYWORDS).get(family_name, ())
        policy = get_packet_policy(family_name)
        if anchor.score < policy.min_anchor_score:
            continue

        included_spans = []
        excluded_spans = []
        for candidate in support_candidates:
            if candidate.span_id == primary.span_id:
                included_spans.append(candidate)
                continue
            quoted, forwarded = _is_quoted_or_forwarded(candidate)
            section_distance = _section_distance(tuple(primary.section_path), tuple(candidate.section_path))
            exclusion_reasons: list[str] = []
            if candidate.authority_score < policy.min_support_authority:
                exclusion_reasons.append("low_authority")
            if quoted and not policy.allow_quoted_support:
                exclusion_reasons.append("quoted_context_disallowed")
            if forwarded and not policy.allow_forwarded_support:
                exclusion_reasons.append("forwarded_context_disallowed")
            if section_distance > policy.max_cross_section_distance:
                exclusion_reasons.append("cross_section_too_far")
            if exclusion_reasons:
                excluded_spans.append((candidate, tuple(dict.fromkeys(exclusion_reasons))))
            else:
                included_spans.append(candidate)
        included_spans = included_spans[: policy.max_support_spans]
        if not included_spans:
            continue

        ordered = sorted(included_spans, key=lambda span: span.span_id)
        span_ids = tuple(span.span_id for span in ordered)
        avg_authority = sum(span.authority_score for span in ordered) / len(ordered)
        section_cohesion = sum(1 for span in ordered if tuple(span.section_path) == tuple(primary.section_path)) / max(1, len(ordered))
        actor_time_bonus = 0.0
        if any((span.author_id and span.author_id == primary.author_id) or (span.speaker_id and span.speaker_id == primary.speaker_id) for span in ordered):
            actor_time_bonus += 0.06
        if any(span.time_anchor_id and span.time_anchor_id == primary.time_anchor_id for span in ordered):
            actor_time_bonus += 0.05
        quoted_count = sum(
            1
            for span in ordered
            if str(span.metadata.get("boundary_class", "")).lower() in {"quoted_context", "forwarded_context", "signature", "disclaimer"}
        )
        quoted_penalty = min(0.2, quoted_count * 0.05)
        cross_section_penalty = 0.12 if section_cohesion < 0.4 else 0.0
        confidence = max(
            0.3,
            min(
                0.95,
                (avg_authority * 0.55)
                + (section_cohesion * 0.2)
                + actor_time_bonus
                + (len(ordered) / max(1, len(spans))) * 0.2
                - quoted_penalty
                - cross_section_penalty,
            ),
        )
        packet_id = f"packet:{family_name}:{packet_index:04d}"
        packet_index += 1
        consumed_anchor_ids.add(primary.span_id)
        anchor_reason_codes = tuple(dict.fromkeys((*anchor.reason_codes, *_anchor_reason_codes(primary))))
        family_hints = tuple(dict.fromkeys((*anchor.family_hints, *_family_hints_for_span(primary))))
        anchor_diag = PacketAnchorDiagnostic(
            anchor_span_id=primary.span_id,
            reason_codes=anchor_reason_codes,
            family_hints=family_hints,
            authority_class=primary.authority_class.value,
            confidence=round(primary.authority_score, 6),
        )

        included: list[PacketInclusionDiagnostic] = []
        all_graph_edges_used: set[str] = set()
        for span in ordered:
            inclusion_reasons: list[str] = []
            if span.span_id == primary.span_id:
                inclusion_reasons.append("cue_seed")
            if tuple(span.section_path) == tuple(primary.section_path):
                inclusion_reasons.append("same_section")
            if (span.author_id and primary.author_id and span.author_id == primary.author_id) or (
                span.speaker_id and primary.speaker_id and span.speaker_id == primary.speaker_id
            ):
                inclusion_reasons.append("same_actor")
            if span.time_anchor_id and primary.time_anchor_id and span.time_anchor_id == primary.time_anchor_id:
                inclusion_reasons.append("same_time")
            if any(keyword in span.normalized_text.lower() for keyword in family_keywords):
                inclusion_reasons.append("supporting_cue_family")
            if not inclusion_reasons:
                inclusion_reasons.append("context_edge")
            edges_used = tuple(
                dict.fromkeys(
                    pair_to_edge_ids.get((primary.span_id, span.span_id), [])
                    + pair_to_edge_ids.get((span.span_id, primary.span_id), [])
                )
            )
            for edge_id in edges_used:
                all_graph_edges_used.add(edge_id)
            role = "direct_support" if span.span_id == primary.span_id else (
                "section_context" if "same_section" in inclusion_reasons else (
                    "actor_context" if "same_actor" in inclusion_reasons else (
                        "time_context" if "same_time" in inclusion_reasons else "context"
                    )
                )
            )
            included.append(
                PacketInclusionDiagnostic(
                    span_id=span.span_id,
                    inclusion_reason_codes=tuple(dict.fromkeys(inclusion_reasons)),
                    graph_edges_used=edges_used,
                    authority_class=span.authority_class.value,
                    confidence=round(span.authority_score, 6),
                    role=role,
                )
            )

        excluded: list[PacketExclusionDiagnostic] = []
        for span, reason_codes in excluded_spans:
            candidate_edges = tuple(
                dict.fromkeys(
                    pair_to_edge_ids.get((primary.span_id, span.span_id), [])
                    + pair_to_edge_ids.get((span.span_id, primary.span_id), [])
                    + span_to_edge_ids.get(span.span_id, [])
                )
            )
            for edge_id in candidate_edges:
                all_graph_edges_used.add(edge_id)
            excluded.append(
                PacketExclusionDiagnostic(
                    span_id=span.span_id,
                    exclusion_reason_codes=reason_codes,
                    graph_edges_considered=candidate_edges,
                )
            )

        anchor_strength = round(primary.authority_score, 6)
        support_density = round(len(included) / max(1, len(spans)), 6)
        authority_bonus = round(max(0.0, avg_authority - 0.5), 6)
        family_consistency = round(section_cohesion, 6)
        section_cohesion_score = round(section_cohesion, 6)
        actor_time_bonus_score = round(actor_time_bonus, 6)
        quoted_context_penalty = round(quoted_penalty, 6)
        cross_section_penalty_score = round(cross_section_penalty, 6)
        score_contributions = (
            PacketScoreContribution("anchor_strength", anchor_strength, ("high_authority_span",)),
            PacketScoreContribution("support_density", support_density, ("context_edge",)),
            PacketScoreContribution("authority_bonus", authority_bonus, ("high_authority_span",)),
            PacketScoreContribution("family_consistency", family_consistency, ("section_label_alignment",)),
            PacketScoreContribution("section_cohesion", section_cohesion_score, ("same_section",)),
            PacketScoreContribution("actor_time_bonus", actor_time_bonus_score, ("same_actor", "same_time")),
            PacketScoreContribution("quoted_context_penalty", -quoted_context_penalty, ("quoted_context_disallowed",)),
            PacketScoreContribution("cross_section_penalty", -cross_section_penalty_score, ("cross_section_too_far",)),
        )
        family_diag = PacketFamilyDiagnostic(
            assigned_family=family_name,
            rationale_codes=family_rationale_codes,
            competing_family_hints=competing_hints,
            family_confidence=round((confidence * 0.65) + (family_confidence * 0.35), 6),
        )
        uncertainty_markers: list[str] = []
        if primary.authority_score < 0.65:
            uncertainty_markers.append("weak_anchor")
        if len(included) < 2:
            uncertainty_markers.append("sparse_support")
        if avg_authority < 0.55:
            uncertainty_markers.append("low_authority_support")
        if quoted_count > 0:
            uncertainty_markers.append("quoted_context_included")
        if competing_hints:
            uncertainty_markers.append("family_conflict")
        if cross_section_penalty > 0:
            uncertainty_markers.append("cross_section_packet")

        packet_diag = PacketDiagnostic(
            packet_id=packet_id,
            anchor=anchor_diag,
            included=tuple(included),
            excluded=tuple(excluded),
            family=family_diag,
            score_contributions=score_contributions,
            graph_edges_used=tuple(sorted(all_graph_edges_used)),
            uncertainty_markers=tuple(dict.fromkeys(uncertainty_markers)),
        )
        packet_diagnostics.append(packet_diag)
        target_claim_family_names = _packet_target_claim_family_names(primary, family_name, competing_hints, family_hints)
        target_field_paths = _packet_target_field_paths(target_claim_family_names)
        packets.append(
            PacketCandidate(
                packet_id=packet_id,
                packet_kind=PacketKind.CLAIM,
                span_ids=span_ids,
                primary_span_id=primary.span_id,
                target_field_paths=target_field_paths,
                target_claim_family_names=target_claim_family_names,
                confidence=confidence,
                authority_class=AuthorityClass.FIRST_PASS if confidence >= 0.6 else AuthorityClass.UNKNOWN,
                metadata={
                    "packet_family": family_name,
                    "packet_policy": document_parse.metadata.get("adapter_context", {}).get("packet_policy"),
                    "span_count": len(span_ids),
                    "packet_diagnostic": packet_diag.to_dict(),
                    "graph_edges_used": list(packet_diag.graph_edges_used),
                    "uncertainty_markers": list(packet_diag.uncertainty_markers),
                },
            )
        )
        diagnostics.append(f"packetized:{family_name}:{len(span_ids)}")
        diagnostics.append(f"packetized_diag:{family_name}:included={len(included)}:excluded={len(excluded)}")

    if not packets and spans:
        primary = sorted(spans, key=lambda span: (span.authority_score, span.span_id), reverse=True)[0]
        family_name, family_rationale_codes, family_confidence, competing_hints = _classify_family(primary, [primary], _PACKET_FAMILY_KEYWORDS)
        packet_id = f"packet:{family_name}:{packet_index:04d}"
        anchor_reason_codes = tuple(dict.fromkeys((*_anchor_reason_codes(primary), "fallback_anchor")))
        anchor_diag = PacketAnchorDiagnostic(
            anchor_span_id=primary.span_id,
            reason_codes=anchor_reason_codes,
            family_hints=_family_hints_for_span(primary),
            authority_class=primary.authority_class.value,
            confidence=round(primary.authority_score, 6),
        )
        included = (
            PacketInclusionDiagnostic(
                span_id=primary.span_id,
                inclusion_reason_codes=("fallback_anchor", "same_section"),
                graph_edges_used=(),
                authority_class=primary.authority_class.value,
                confidence=round(primary.authority_score, 6),
                role="direct_support",
            ),
        )
        score_contributions = (
            PacketScoreContribution("anchor_strength", round(primary.authority_score, 6), ("fallback_anchor",)),
            PacketScoreContribution("support_density", round(1 / max(1, len(spans)), 6), ("fallback_anchor",)),
            PacketScoreContribution("authority_bonus", round(max(0.0, primary.authority_score - 0.5), 6), ("fallback_anchor",)),
            PacketScoreContribution("family_consistency", 1.0, ("fallback_anchor",)),
            PacketScoreContribution("section_cohesion", 1.0, ("same_section",)),
        )
        family_diag = PacketFamilyDiagnostic(
            assigned_family=family_name,
            rationale_codes=tuple(dict.fromkeys((*family_rationale_codes, "fallback_classification"))),
            competing_family_hints=competing_hints,
            family_confidence=round(family_confidence, 6),
        )
        uncertainty_markers: list[str] = ["fallback_packet"]
        if primary.authority_score < 0.6:
            uncertainty_markers.append("weak_anchor")
        packet_diag = PacketDiagnostic(
            packet_id=packet_id,
            anchor=anchor_diag,
            included=included,
            excluded=(),
            family=family_diag,
            score_contributions=score_contributions,
            graph_edges_used=(),
            uncertainty_markers=tuple(dict.fromkeys(uncertainty_markers)),
        )
        packet_diagnostics.append(packet_diag)
        target_claim_family_names = _packet_target_claim_family_names(primary, family_name, competing_hints, _family_hints_for_span(primary))
        target_field_paths = _packet_target_field_paths(target_claim_family_names)
        packets.append(
            PacketCandidate(
                packet_id=packet_id,
                packet_kind=PacketKind.CLAIM,
                span_ids=(primary.span_id,),
                primary_span_id=primary.span_id,
                target_field_paths=target_field_paths,
                target_claim_family_names=target_claim_family_names,
                confidence=max(0.3, min(0.8, primary.authority_score)),
                authority_class=AuthorityClass.FIRST_PASS if primary.authority_score >= 0.6 else AuthorityClass.UNKNOWN,
                metadata={
                    "packet_family": family_name,
                    "packet_policy": document_parse.metadata.get("adapter_context", {}).get("packet_policy"),
                    "span_count": 1,
                    "packet_diagnostic": packet_diag.to_dict(),
                    "graph_edges_used": [],
                    "uncertainty_markers": list(packet_diag.uncertainty_markers),
                },
            )
        )
        diagnostics.append(f"packetized_fallback:{family_name}:1")

    debug_bundle = build_packet_debug_bundle(packet_diagnostics)
    return PacketizerResult(
        packets=tuple(sorted(packets, key=lambda packet: packet.packet_id)),
        diagnostics=tuple(diagnostics),
        packet_debug_bundle=debug_bundle,
    )
