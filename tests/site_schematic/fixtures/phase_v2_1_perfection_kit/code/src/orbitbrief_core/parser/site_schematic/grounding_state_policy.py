from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class GroundingStateDecision:
    state: str
    confidence: float
    reasons: List[str]


def choose_grounding_state(
    *,
    legend_match_score: float,
    text_association_score: float,
    connector_score: float,
    room_device_score: float,
    page_type_compatibility: float,
) -> GroundingStateDecision:
    """
    Deterministic, fail-closed state policy for V2.1.
    """
    reasons: List[str] = []
    total = (
        0.35 * legend_match_score
        + 0.20 * text_association_score
        + 0.20 * connector_score
        + 0.15 * room_device_score
        + 0.10 * page_type_compatibility
    )

    if total >= 0.82:
        reasons.append("strong_total_support")
        return GroundingStateDecision("grounded", total, reasons)

    # High legend/text but weak connector/context should stay ambiguous, not forced grounded
    if legend_match_score >= 0.75 and text_association_score >= 0.6:
        reasons.append("strong_semantic_but_incomplete_context")
        return GroundingStateDecision("ambiguous", total, reasons)

    reasons.append("insufficient_support")
    return GroundingStateDecision("unresolved", total, reasons)
