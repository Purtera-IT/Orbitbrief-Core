from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import ContradictionFlag, PlannerInput, PlannerOutput, ProfessionalServicesPreDraft
from .shared import make_id, stable_value_hash, utc_now


def build_planner_input(
    domain_id: str,
    config_snapshot_ref,
    role_graphs,
    field_claims,
    authority_weights,
    review_flags,
    contradiction_flags=None,
    planner_notes=None,
) -> PlannerInput:
    return PlannerInput(
        domain_id=domain_id,
        config_snapshot_ref=config_snapshot_ref,
        role_graphs=role_graphs,
        field_claims=field_claims,
        authority_weights=authority_weights,
        review_flags=review_flags,
        contradiction_flags=contradiction_flags or [],
        planner_notes=planner_notes or [],
    )


def detect_contradictions(field_claims) -> list[ContradictionFlag]:
    grouped = defaultdict(list)
    for claim in field_claims:
        if claim.target_layer != "pre_field":
            continue
        grouped[claim.field_name].append(claim)
    contradictions: list[ContradictionFlag] = []
    for field_name, claims in grouped.items():
        hashes = {stable_value_hash(claim.normalized_value) for claim in claims}
        if len(hashes) > 1:
            contradictions.append(
                ContradictionFlag(
                    id=make_id("contradiction"),
                    domain_id="professional_services",
                    field_name=field_name,
                    conflicting_claim_refs=[claim.id for claim in claims],
                    severity="medium",
                    resolution_status="open",
                    notes=f"Conflicting values detected for {field_name}.",
                    created_at=utc_now(),
                )
            )
    return contradictions


def assemble_canonical_pre_draft(field_claims, authority_weights, contradictions: list[ContradictionFlag]) -> ProfessionalServicesPreDraft:
    weight_lookup = {weight.id: weight for weight in authority_weights}
    by_field: dict[str, list[Any]] = defaultdict(list)
    contradiction_fields = {flag.field_name for flag in contradictions}
    for claim in field_claims:
        if claim.target_layer != "pre_field" or claim.field_name in contradiction_fields:
            continue
        direct_weight = 0.5
        if claim.authority_weight_ref and claim.authority_weight_ref in weight_lookup:
            direct_weight = weight_lookup[claim.authority_weight_ref].weight
        score = direct_weight + claim.confidence
        by_field[claim.field_name].append((score, claim.normalized_value))
    payload = {}
    for field_name, scored_values in by_field.items():
        scored_values.sort(key=lambda item: item[0], reverse=True)
        payload[field_name] = scored_values[0][1]
    return ProfessionalServicesPreDraft(**payload)


def merge_review_flags(*flag_groups) -> list[Any]:
    merged = []
    seen = set()
    for group in flag_groups:
        for flag in group:
            key = (flag.code, flag.message, tuple(flag.evidence_refs))
            if key in seen:
                continue
            seen.add(key)
            merged.append(flag)
    return merged


def build_planner_output(planner_input: PlannerInput) -> PlannerOutput:
    contradictions = detect_contradictions(planner_input.field_claims)
    draft = assemble_canonical_pre_draft(planner_input.field_claims, planner_input.authority_weights, contradictions)
    review_flags = merge_review_flags(planner_input.review_flags)
    return PlannerOutput(
        domain_id=planner_input.domain_id,
        config_snapshot_ref=planner_input.config_snapshot_ref,
        canonical_pre_draft=draft,
        contradiction_flags=contradictions,
        review_flags=review_flags,
        planner_summary=f"Planner assembled runtime PRE draft from {len(planner_input.field_claims)} claims.",
        confidence=0.7 if not contradictions else 0.45,
    )
