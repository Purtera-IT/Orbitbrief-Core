from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class ConnectorContextScore:
    score: float
    reasons: List[str]


def score_connector_context(
    *,
    connector_candidate_count: int = 0,
    leader_attachment_count: int = 0,
    riser_context: bool = False,
    rack_pathway_context: bool = False,
    equipment_detail_context: bool = False,
) -> ConnectorContextScore:
    reasons: List[str] = []
    score = 0.0
    if connector_candidate_count > 0:
        score += min(0.35, 0.1 * connector_candidate_count)
        reasons.append("connector_candidates")
    if leader_attachment_count > 0:
        score += min(0.2, 0.1 * leader_attachment_count)
        reasons.append("leader_attachments")
    if riser_context:
        score += 0.15
        reasons.append("riser_context")
    if rack_pathway_context:
        score += 0.15
        reasons.append("rack_pathway_context")
    if equipment_detail_context:
        score += 0.1
        reasons.append("equipment_detail_context")
    return ConnectorContextScore(min(score, 1.0), reasons)
