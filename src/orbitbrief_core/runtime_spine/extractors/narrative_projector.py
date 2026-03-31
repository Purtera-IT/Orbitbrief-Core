from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
