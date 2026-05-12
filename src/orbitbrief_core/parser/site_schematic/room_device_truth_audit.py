from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoomTruthAudit:
    evidence_truth_ok: bool
    score_distribution_ok: bool
    reasons: tuple[str, ...]


def audit_room_device_truth(
    *,
    association_rate: float,
    room_assoc_scores: list[float],
    near_room_label_hits: int,
    same_region_hits: int,
    leader_attached_hits: int,
) -> RoomTruthAudit:
    reasons: list[str] = []
    evidence_support = int(near_room_label_hits) + int(same_region_hits) + int(leader_attached_hits)
    score_distribution_ok = True
    if room_assoc_scores:
        unique_scores = len(set(round(float(score), 3) for score in room_assoc_scores))
        if unique_scores <= 2 and float(association_rate) >= 0.9:
            score_distribution_ok = False
            reasons.append("collapsed_room_assoc_score_distribution")
    evidence_truth_ok = True
    if float(association_rate) >= 0.9 and evidence_support == 0:
        evidence_truth_ok = False
        reasons.append("high_room_assoc_without_evidence")
    return RoomTruthAudit(evidence_truth_ok=evidence_truth_ok, score_distribution_ok=score_distribution_ok, reasons=tuple(reasons))
