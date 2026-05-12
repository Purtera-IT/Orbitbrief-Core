from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectorTruthAudit:
    evidence_truth_ok: bool
    reasons: tuple[str, ...]


def audit_connector_truth(
    *,
    connector_quality_rate: float,
    connector_candidate_rate: float,
    connector_scores: list[float],
    leader_attachment_hits: int,
) -> ConnectorTruthAudit:
    reasons: list[str] = []
    evidence_truth_ok = True
    max_score = max([float(score) for score in connector_scores], default=0.0)
    if float(connector_quality_rate) >= 0.98 and float(connector_candidate_rate) < 0.05 and int(leader_attachment_hits) == 0:
        evidence_truth_ok = False
        reasons.append("connector_quality_too_high_for_low_evidence")
    if float(connector_quality_rate) >= 0.98 and max_score < 0.3:
        evidence_truth_ok = False
        reasons.append("connector_quality_too_high_for_low_scores")
    return ConnectorTruthAudit(evidence_truth_ok=evidence_truth_ok, reasons=tuple(reasons))
