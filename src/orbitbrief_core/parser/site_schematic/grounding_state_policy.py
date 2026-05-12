from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroundingStateDecision:
    state: str
    confidence: float
    reasons: tuple[str, ...]


def choose_grounding_state(
    *,
    legend_match_score: float,
    text_association_score: float,
    connector_score: float,
    room_device_score: float,
    page_type_compatibility: float,
) -> GroundingStateDecision:
    reasons: list[str] = []
    total = (
        0.35 * float(legend_match_score)
        + 0.20 * float(text_association_score)
        + 0.20 * float(connector_score)
        + 0.15 * float(room_device_score)
        + 0.10 * float(page_type_compatibility)
    )
    if total >= 0.4 or (
        legend_match_score >= 0.45
        and (text_association_score >= 0.2 or connector_score >= 0.45 or room_device_score >= 0.55)
    ):
        reasons.append("strong_total_support")
        return GroundingStateDecision("grounded", min(1.0, total), tuple(reasons))
    if total >= 0.2 or legend_match_score >= 0.2 or text_association_score >= 0.2:
        reasons.append("strong_semantic_but_incomplete_context")
        return GroundingStateDecision("ambiguous", min(1.0, total), tuple(reasons))
    reasons.append("insufficient_support")
    return GroundingStateDecision("unresolved", max(0.0, total), tuple(reasons))
