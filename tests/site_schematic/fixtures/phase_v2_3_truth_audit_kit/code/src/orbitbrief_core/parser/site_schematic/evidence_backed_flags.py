from __future__ import annotations

from typing import Dict


def evidence_backed_connector_ok(
    *,
    connector_context_score: float,
    connector_candidate_count: int,
    leader_attachment_count: int,
) -> bool:
    return connector_context_score >= 0.55 and (connector_candidate_count > 0 or leader_attachment_count > 0)


def evidence_backed_room_assoc_ok(
    *,
    room_device_association_score: float,
    near_room_label: bool,
    same_region: bool,
    leader_attached: bool,
) -> bool:
    strong_locality = near_room_label or same_region or leader_attached
    return room_device_association_score >= 0.55 and strong_locality


def evidence_backed_grounded_ok(
    *,
    grounding_state: str,
    legend_match_score: float,
    legend_text_association_score: float,
    connector_context_score: float,
    room_device_association_score: float,
    page_type_compatibility: float,
) -> bool:
    support = (
        0.35 * legend_match_score
        + 0.20 * legend_text_association_score
        + 0.20 * connector_context_score
        + 0.15 * room_device_association_score
        + 0.10 * page_type_compatibility
    )
    if grounding_state != "grounded":
        return True
    return support >= 0.72
