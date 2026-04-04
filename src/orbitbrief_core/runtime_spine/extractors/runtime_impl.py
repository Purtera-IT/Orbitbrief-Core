from __future__ import annotations

from typing import Any

from .narrative_claim_ontology import NARRATIVE_CLAIM_FAMILIES


_PACKET_FAMILY_TO_CLAIM = {
    "scope_packet": ("scope_included_claim", "scope_included"),
    "exclusion_packet": ("scope_excluded_claim", "scope_excluded"),
    "assumption_packet": ("assumption_claim", "assumptions"),
    "risk_packet": ("risk_claim", "risks"),
    "dependency_packet": ("third_party_dependency_claim", "dependencies"),
    "site_packet": ("site_location_claim", "site_locations"),
    "quantity_packet": ("known_quantity_claim", "known_quantities"),
    "deliverable_packet": ("deliverable_claim", "deliverables_required"),
    "schedule_packet": ("schedule_claim", "schedule"),
    "responsibility_packet": ("customer_responsibility_claim", "customer_responsibilities"),
    "open_question_packet": ("open_question_claim", "open_questions"),
}


def run_narrative_extractor(*, role_id: str, modality: str, packet_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Packet-driven deterministic narrative extractor for managed-services text lane."""
    field_claims: list[dict[str, Any]] = []
    for packet in packet_candidates:
        metadata = packet.get("metadata", {}) if isinstance(packet, dict) else {}
        if not isinstance(metadata, dict):
            continue
        packet_family = str(metadata.get("packet_family", "")).strip()
        mapping = _PACKET_FAMILY_TO_CLAIM.get(packet_family)
        if mapping is None:
            continue
        claim_family, target_field = mapping
        if claim_family not in NARRATIVE_CLAIM_FAMILIES:
            continue
        confidence = float(packet.get("confidence", 0.5)) if isinstance(packet.get("confidence"), (int, float)) else 0.5
        span_ids = packet.get("span_ids", [])
        if isinstance(span_ids, tuple):
            span_ids = list(span_ids)
        if not isinstance(span_ids, list):
            span_ids = []
        field_claims.append(
            {
                "claim_id": f"claim:{packet.get('packet_id', claim_family)}",
                "claim_family": claim_family,
                "target_field": target_field,
                "target_field_path": target_field,
                "candidate_value": f"{packet_family}:{len(span_ids)}",
                "confidence": max(0.0, min(1.0, confidence)),
                "evidence_span_ids": span_ids,
                "packet_id": packet.get("packet_id"),
                "packet_family": packet_family,
            }
        )

    return {
        "role_id": role_id,
        "modality": modality,
        "packet_count": len(packet_candidates),
        "field_claims": field_claims,
        "emits_business_claims": True,
    }


def run_intake_only_extractor(
    *,
    role_id: str,
    modality: str,
    reason: str | None = None,
    reason_codes: tuple[str, ...] | list[str] | None = None,
    pipeline_state: str = "intake_only",
    packet_count: int = 0,
) -> dict[str, Any]:
    """Deterministic intake-only fallback result envelope."""
    reason_codes_tuple = tuple(reason_codes or ())
    return {
        "role_id": role_id,
        "modality": modality,
        "lane": pipeline_state,
        "reason": reason or "fallback_policy",
        "reason_codes": list(reason_codes_tuple),
        "packet_count": int(packet_count),
        "review_required": True,
        "field_claims": [],
        "emits_business_claims": False,
    }
