from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ConnectorGroundingRefinement:
    adjusted_score: float
    reasons: List[str]


def refine_with_connector_context(
    *,
    base_score: float,
    has_connector_candidate: bool,
    has_leader_attachment: bool,
    riser_context: bool,
    rack_pathway_context: bool,
) -> ConnectorGroundingRefinement:
    reasons: List[str] = []
    score = base_score
    if has_connector_candidate:
        score += 0.15
        reasons.append("connector_candidate")
    if has_leader_attachment:
        score += 0.1
        reasons.append("leader_attachment")
    if riser_context:
        score += 0.1
        reasons.append("riser_context")
    if rack_pathway_context:
        score += 0.1
        reasons.append("rack_pathway_context")
    return ConnectorGroundingRefinement(min(score, 1.0), reasons)
