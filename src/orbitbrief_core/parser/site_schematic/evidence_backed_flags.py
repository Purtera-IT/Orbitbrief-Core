from __future__ import annotations


def evidence_backed_connector_ok(
    *,
    connector_context_score: float,
    connector_candidate_count: int,
    leader_attachment_count: int,
) -> bool:
    return (
        float(connector_context_score) >= 0.15
        and (int(connector_candidate_count) > 0 or int(leader_attachment_count) > 0)
    )


def evidence_backed_room_assoc_ok(
    *,
    room_device_association_score: float,
    near_room_label: bool,
    same_region: bool,
    leader_attached: bool,
) -> bool:
    strong_locality = bool(near_room_label) or bool(same_region) or bool(leader_attached)
    return float(room_device_association_score) >= 0.35 and strong_locality


def evidence_backed_grounded_ok(
    *,
    grounding_state: str,
    legend_match_score: float,
    legend_text_association_score: float,
    connector_context_score: float,
    room_device_association_score: float,
    page_type_compatibility: float,
) -> bool:
    if grounding_state != "grounded":
        return True
    support = (
        0.35 * float(legend_match_score)
        + 0.20 * float(legend_text_association_score)
        + 0.20 * float(connector_context_score)
        + 0.15 * float(room_device_association_score)
        + 0.10 * float(page_type_compatibility)
    )
    return support >= 0.25
