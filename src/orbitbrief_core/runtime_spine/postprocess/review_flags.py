from __future__ import annotations

from .base import ContradictionGroup, PostprocessPolicy, ProcessedClaim, ReviewFlag


def generate_review_flags(
    *,
    claims: tuple[ProcessedClaim, ...],
    contradiction_groups: tuple[ContradictionGroup, ...],
    policy: PostprocessPolicy,
) -> tuple[ReviewFlag, ...]:
    flags: list[ReviewFlag] = []
    verification_threshold = float(policy.review_rules.get("verification_confidence_threshold", 0.55))
    stronger_source_threshold = float(policy.review_rules.get("stronger_source_confidence_threshold", 0.40))

    for claim in claims:
        if claim.confidence < verification_threshold:
            flags.append(
                ReviewFlag(
                    flag_id=f"flag:{claim.claim_id}:verification_needed",
                    code="verification_needed",
                    severity="warning",
                    message="Claim confidence is below verification threshold.",
                    claim_ids=(claim.claim_id,),
                )
            )
        if claim.confidence < stronger_source_threshold:
            flags.append(
                ReviewFlag(
                    flag_id=f"flag:{claim.claim_id}:stronger_source_needed",
                    code="stronger_source_needed",
                    severity="warning",
                    message="Claim requires stronger source evidence.",
                    claim_ids=(claim.claim_id,),
                )
            )
        if not claim.evidence_span_ids:
            flags.append(
                ReviewFlag(
                    flag_id=f"flag:{claim.claim_id}:low_evidence",
                    code="low_evidence",
                    severity="warning",
                    message="Claim has no evidence references after processing.",
                    claim_ids=(claim.claim_id,),
                )
            )

    for group in contradiction_groups:
        flags.append(
            ReviewFlag(
                flag_id=f"flag:{group.contradiction_id}:conflicting_evidence",
                code="conflicting_evidence",
                severity="high",
                message="Conflicting claim values detected for same semantic slot.",
                claim_ids=group.claim_ids,
                metadata={"contradiction_id": group.contradiction_id},
            )
        )

    return tuple(sorted(flags, key=lambda flag: flag.flag_id))
