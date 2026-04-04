from __future__ import annotations

from collections import defaultdict

from .base import ProcessedClaim, RejectedClaim


def dedupe_claims(
    claims: tuple[ProcessedClaim, ...],
) -> tuple[tuple[ProcessedClaim, ...], list[RejectedClaim]]:
    groups: dict[tuple[str, str, str], list[ProcessedClaim]] = defaultdict(list)
    for claim in claims:
        key = (claim.claim_family, claim.target_field_path, str(claim.normalized_value))
        groups[key].append(claim)

    deduped: list[ProcessedClaim] = []
    rejected: list[RejectedClaim] = []
    for _, group in groups.items():
        ordered = sorted(
            group,
            key=lambda claim: (
                -len(claim.evidence_span_ids),
                -claim.confidence,
                claim.claim_id,
            ),
        )
        winner = ordered[0]
        merged_sources: list[str] = []
        for item in ordered:
            merged_sources.extend(item.source_claim_ids or (item.claim_id,))
        deduped.append(
            ProcessedClaim(
                claim_id=winner.claim_id,
                claim_family=winner.claim_family,
                target_field=winner.target_field,
                target_field_path=winner.target_field_path,
                normalized_value=winner.normalized_value,
                confidence=winner.confidence,
                evidence_span_ids=winner.evidence_span_ids,
                source_claim_ids=tuple(sorted(set(merged_sources))),
                metadata=winner.metadata,
            )
        )
        for loser in ordered[1:]:
            rejected.append(
                RejectedClaim(
                    claim_id=loser.claim_id,
                    reason_code="duplicate_merged",
                    message=f"Claim merged into {winner.claim_id}.",
                    metadata={"kept_claim_id": winner.claim_id},
                )
            )
    deduped_sorted = tuple(sorted(deduped, key=lambda claim: claim.claim_id))
    return deduped_sorted, rejected
