from __future__ import annotations

from collections import defaultdict

from .base import ContradictionGroup, ProcessedClaim


def group_contradictions(claims: tuple[ProcessedClaim, ...]) -> tuple[ContradictionGroup, ...]:
    by_field_path: dict[str, list[ProcessedClaim]] = defaultdict(list)
    for claim in claims:
        by_field_path[claim.target_field_path].append(claim)

    groups: list[ContradictionGroup] = []
    counter = 0
    for field_path, members in sorted(by_field_path.items()):
        distinct_values = {str(member.normalized_value) for member in members}
        if len(distinct_values) <= 1:
            continue
        claim_ids = tuple(sorted(member.claim_id for member in members))
        groups.append(
            ContradictionGroup(
                contradiction_id=f"contradiction:{field_path}:{counter:04d}",
                target_field_path=field_path,
                claim_ids=claim_ids,
                reason_code="conflicting_values_for_field_path",
                metadata={"distinct_value_count": len(distinct_values)},
            )
        )
        counter += 1
    return tuple(groups)
