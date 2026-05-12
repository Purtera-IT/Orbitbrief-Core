from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Protocol

from .narrative_claim_ontology import FieldClaim, InternalClaim


@dataclass(slots=True)
class InternalNarrativeClaim:
    claim_family: str
    value: Any
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)


def _append_value(payload: dict[str, Any], field: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    existing = payload.get(field)
    if existing is None:
        payload[field] = value
        return
    if isinstance(existing, list):
        if isinstance(value, list):
            existing.extend(value)
        else:
            existing.append(value)
        payload[field] = existing
        return
    if existing != value:
        payload[field] = [existing, value] if not isinstance(value, list) else [existing, *value]


def project_to_rich_txt_pre(claims: list[InternalNarrativeClaim]) -> dict[str, Any]:
    mapping = {
        "project_identity": "project_name",
        "customer_identity": "customer_name",
        "request_context": "request_source",
        "business_driver": "business_driver",
        "project_summary": "project_summary",
        "success_criteria": "success_criteria",
        "site_count_claim": "site_count",
        "site_location_claim": "site_locations",
        "site_type_claim": "site_types",
        "site_topology_claim": "site_topology",
        "site_condition_claim": "site_conditions",
        "scope_included_claim": "scope_included",
        "scope_excluded_claim": "scope_excluded",
        "scope_by_others_claim": "scope_by_others",
        "known_quantity_claim": "known_quantities",
        "technical_environment_claim": "technical_environment",
        "schedule_claim": "schedule",
        "access_logistics_claim": "access_and_logistics",
        "deliverable_claim": "deliverables_required",
        "testing_acceptance_claim": "testing_and_acceptance",
        "customer_responsibility_claim": "customer_responsibilities",
        "customer_input_required_claim": "customer_inputs_required",
        "customer_document_required_claim": "customer_documents_required",
        "customer_material_claim": "customer_provided_materials",
        "third_party_dependency_claim": "third_party_dependencies",
        "commercial_structure_claim": "commercial_structure",
        "assumption_claim": "assumptions",
        "risk_claim": "risks",
        "open_question_claim": "open_questions",
        "readiness_gap_claim": "readiness_gaps",
        "contact_claim": "primary_customer_contact",
        "decision_maker_claim": "decision_makers",
        "sow_author_note_claim": "notes_for_sow_author",
    }
    payload: dict[str, Any] = {}
    for claim in claims:
        target = mapping.get(claim.claim_family)
        if target:
            _append_value(payload, target, claim.value)
    return payload


def project_to_slim_pre(claims: list[InternalNarrativeClaim]) -> dict[str, Any]:
    mapping = {
        "project_summary": "project_summary",
        "site_count_claim": "site_count",
        "site_location_claim": "location_details",
        "scope_included_claim": "scope_tasks_requested",
        "known_quantity_claim": "known_quantities",
        "customer_material_claim": "customer_provided_materials",
        "access_logistics_claim": "access_constraints",
        "testing_acceptance_claim": "testing_requirements",
        "deliverable_claim": "deliverables_needed",
        "assumption_claim": "known_assumptions",
        "scope_excluded_claim": "known_exclusions",
        "scope_by_others_claim": "known_exclusions",
        "open_question_claim": "open_questions",
    }
    payload: dict[str, Any] = {}
    for claim in claims:
        target = mapping.get(claim.claim_family)
        if target:
            _append_value(payload, target, claim.value)
    return payload


def project_to_post_hints(claims: list[InternalNarrativeClaim]) -> dict[str, Any]:
    mapping = {
        "project_summary": "scope_overview",
        "scope_included_claim": "detailed_scope_of_services",
        "deliverable_claim": "deliverables",
        "assumption_claim": "assumptions",
        "customer_responsibility_claim": "customer_responsibilities",
        "scope_excluded_claim": "out_of_scope",
        "risk_claim": "risks_or_dependencies",
        "success_criteria": "completion_criteria",
        "open_question_claim": "open_items",
    }
    payload: dict[str, Any] = {}
    for claim in claims:
        target = mapping.get(claim.claim_family)
        if target:
            _append_value(payload, target, claim.value)
    return payload


_CLAIM_FAMILY_TO_FIELD_PATH: dict[str, str] = {
    "customer_identity": "customer_name",
    "project_identity": "project_name",
    "project_summary": "project_summary",
    "scope_included_claim": "scope_included",
    "scope_excluded_claim": "scope_excluded",
    "assumption_claim": "assumptions",
    "risk_claim": "risks",
    "third_party_dependency_claim": "dependencies",
    "access_logistics_claim": "access_and_logistics",
    "site_location_claim": "site_locations",
    "site_count_claim": "site_count",
    "known_quantity_claim": "known_quantities",
    "deliverable_claim": "deliverables_required",
    "schedule_claim": "schedule",
    "customer_responsibility_claim": "customer_responsibilities",
    "commercial_structure_claim": "commercial_structure.pricing_model",
    "contact_claim": "primary_customer_contact",
    "open_question_claim": "open_questions",
    "drawing_metadata_claim": "drawing_packet_metadata",
    "site_topology_claim": "site_profile_from_drawings",
    "network_room_claim": "site_profile_from_drawings",
    "equipment_reference_claim": "known_quantities",
    "scope_note_claim": "scope_included",
    "constructability_claim": "access_and_logistics",
    "revision_change_claim": "drawing_packet_metadata",
    "topology_hint_claim": "site_profile_from_drawings",
}

_CAD_PACKET_FAMILIES: frozenset[str] = frozenset(
    {
        "drawing_metadata_packet",
        "site_identity_packet",
        "network_room_or_closet_packet",
        "equipment_reference_packet",
        "note_scope_packet",
        "revision_change_packet",
        "topology_hint_packet",
        "constructability_packet",
        "known_quantity_packet",
    }
)
_CAD_ALLOWED_FIELD_PATHS: frozenset[str] = frozenset(
    {
        "site_locations",
        "known_quantities",
        "scope_included",
        "assumptions",
        "risks",
        "dependencies",
        "access_and_logistics",
        "drawing_packet_metadata",
        "site_profile_from_drawings",
    }
)

_CAD_SCOPE_BEARING_RE = re.compile(r"\b(?:scope|in scope|include|included|support|coverage|install|replace)\b", flags=re.IGNORECASE)
_CAD_CONSTRUCTABILITY_RISK_RE = re.compile(r"\b(?:risk|blocker|constraint|clearance|readiness|unsafe)\b", flags=re.IGNORECASE)
_CAD_CONSTRUCTABILITY_DEP_RE = re.compile(r"\b(?:depend|approval|vendor|carrier|permit|coordination|landlord)\b", flags=re.IGNORECASE)
_CAD_CONSTRUCTABILITY_ACCESS_RE = re.compile(r"\b(?:access|badge|escort|after-hours|loading|logistics|entry)\b", flags=re.IGNORECASE)
_CAD_TOPOLOGY_HINT_RE = re.compile(r"\b(?:topology|uplink|trunk|cross-connect|neighbor|served by|distribution)\b", flags=re.IGNORECASE)
_CAD_METADATA_NOISE_RE = re.compile(r"\b(?:legend|symbol table|boilerplate|stamp|not for construction)\b", flags=re.IGNORECASE)


def _normalize_field_path(field_path: str) -> str:
    value = str(field_path or "").strip()
    while "[]" in value:
        value = value.replace("[]", "")
    return value


def _cad_projection_allowed(claim: InternalClaim, field_path: str) -> bool:
    if claim.packet_family not in _CAD_PACKET_FAMILIES:
        return True
    if claim.confidence < 0.72:
        return False
    if claim.status in {"ambiguous", "needs_review"}:
        return False
    if claim.verification_needed or claim.stronger_source_needed:
        return False
    normalized = _normalize_field_path(field_path)
    return normalized in _CAD_ALLOWED_FIELD_PATHS


class ProjectionPolicy(Protocol):
    def projection_targets_for_claim_family(self, claim_family: str) -> tuple[str, ...]:
        ...


def _field_paths_for_claim_family(claim_family: str, projection_policy: ProjectionPolicy | None) -> tuple[str, ...]:
    if projection_policy is not None:
        projected = tuple(path for path in projection_policy.projection_targets_for_claim_family(claim_family) if path)
        if projected:
            return projected
    if claim_family == "drawing_metadata_claim":
        return ("drawing_packet_metadata", "site_profile_from_drawings")
    if claim_family == "network_room_claim":
        return ("site_profile_from_drawings", "access_and_logistics")
    if claim_family == "constructability_claim":
        return ("access_and_logistics", "risks", "dependencies")
    fallback = _CLAIM_FAMILY_TO_FIELD_PATH.get(claim_family)
    return (fallback,) if fallback else ()


def _project_field_path_for_claim(claim: InternalClaim, field_path: str) -> bool:
    if not _cad_projection_allowed(claim, field_path):
        return False
    if claim.packet_family in _CAD_PACKET_FAMILIES:
        text = str(claim.claim_body or "")
        if _CAD_METADATA_NOISE_RE.search(text):
            return False
        if claim.claim_family == "drawing_metadata_claim":
            if field_path == "site_profile_from_drawings":
                return bool(re.search(r"\b(?:site|location|building|floor|room|closet|mdf|idf)\b", text, flags=re.IGNORECASE))
            return field_path == "drawing_packet_metadata"
        if claim.claim_family == "network_room_claim":
            if field_path == "access_and_logistics":
                return bool(_CAD_CONSTRUCTABILITY_ACCESS_RE.search(text))
            return field_path == "site_profile_from_drawings"
        if claim.claim_family == "equipment_reference_claim":
            return field_path == "known_quantities"
        if claim.claim_family == "scope_note_claim":
            return field_path == "scope_included" and bool(_CAD_SCOPE_BEARING_RE.search(text))
        if claim.claim_family == "constructability_claim":
            if field_path == "access_and_logistics":
                return bool(_CAD_CONSTRUCTABILITY_ACCESS_RE.search(text) or _CAD_CONSTRUCTABILITY_RISK_RE.search(text))
            if field_path == "risks":
                return bool(_CAD_CONSTRUCTABILITY_RISK_RE.search(text))
            if field_path == "dependencies":
                return bool(_CAD_CONSTRUCTABILITY_DEP_RE.search(text))
            return False
        if claim.claim_family == "revision_change_claim":
            return field_path == "drawing_packet_metadata"
        if claim.claim_family == "topology_hint_claim":
            return field_path == "site_profile_from_drawings" and bool(_CAD_TOPOLOGY_HINT_RE.search(text))
    if claim.claim_family != "schedule_claim":
        return True
    schedule_class = str(claim.metadata.get("schedule_semantic_class") or "")
    if field_path == "completion_criteria[]":
        return schedule_class == "true_schedule_commitment"
    return True


def project_internal_claims_to_field_claims(
    claims: tuple[InternalClaim, ...] | list[InternalClaim],
    *,
    projection_policy: ProjectionPolicy | None = None,
) -> tuple[FieldClaim, ...]:
    projected: list[FieldClaim] = []
    for claim in claims:
        field_paths = _field_paths_for_claim_family(claim.claim_family, projection_policy)
        if not field_paths:
            continue
        for field_path in field_paths:
            if not _project_field_path_for_claim(claim, field_path):
                continue
            projected.append(
                FieldClaim(
                    claim_family=claim.claim_family,
                    field_path=field_path,
                    value=claim.claim_body,
                    source_claim_id=claim.claim_id,
                    evidence=claim.evidence,
                    confidence=claim.confidence,
                    status=claim.status,
                    projection_reason_codes=(
                        "compiled_projection_rule" if projection_policy is not None else "family_to_field_projection",
                    ),
                    metadata={
                        "packet_id": claim.packet_id,
                        "packet_family": claim.packet_family,
                        "verification_needed": claim.verification_needed,
                        "stronger_source_needed": claim.stronger_source_needed,
                        **dict(claim.metadata),
                    },
                )
            )
    return tuple(projected)
