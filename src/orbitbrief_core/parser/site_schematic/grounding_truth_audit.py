from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TruthAuditResult:
    suspicious_uniform_grounding: bool
    impossible_connector_success: bool
    impossible_room_assoc_success: bool
    reasons: tuple[str, ...]


def audit_packet_truth_signals(
    *,
    candidate_symbol_count: int,
    grounded_symbol_count: int,
    unresolved_symbol_count: int,
    connector_topology_candidate_rate: float,
    connector_grounding_quality_rate: float,
    room_device_association_rate: float,
    required_page_types: list[str],
    satisfied_page_types: list[str],
    grounded_rows: list[dict[str, Any]],
) -> TruthAuditResult:
    reasons: list[str] = []
    suspicious_uniform_grounding = False
    impossible_connector_success = False
    impossible_room_assoc_success = False

    if (
        required_page_types
        and candidate_symbol_count >= 1000
        and grounded_symbol_count == candidate_symbol_count
        and unresolved_symbol_count == 0
        and connector_grounding_quality_rate >= 0.99
        and room_device_association_rate >= 0.99
    ):
        if grounded_rows:
            states = {row.get("grounding_state") for row in grounded_rows}
            connector_flags = {row.get("connector_grounding_ok") for row in grounded_rows}
            room_flags = {row.get("room_device_association_ok") for row in grounded_rows}
            if len(states) == 1 and len(connector_flags) == 1 and len(room_flags) == 1:
                suspicious_uniform_grounding = True
                reasons.append("uniform_grounding_pattern")

    if connector_topology_candidate_rate < 0.02 and connector_grounding_quality_rate >= 0.99:
        impossible_connector_success = True
        reasons.append("connector_quality_too_high_for_low_connector_evidence")

    if room_device_association_rate >= 0.95 and grounded_rows:
        assoc_scores = [float(row.get("room_device_association_score", 0.0) or 0.0) for row in grounded_rows]
        if assoc_scores and max(assoc_scores) < 0.6:
            impossible_room_assoc_success = True
            reasons.append("room_assoc_flags_too_high_for_low_scores")

    if required_page_types == [] and satisfied_page_types == []:
        reasons.append("empty_required_hardpage_set")

    return TruthAuditResult(
        suspicious_uniform_grounding=suspicious_uniform_grounding,
        impossible_connector_success=impossible_connector_success,
        impossible_room_assoc_success=impossible_room_assoc_success,
        reasons=tuple(reasons),
    )
