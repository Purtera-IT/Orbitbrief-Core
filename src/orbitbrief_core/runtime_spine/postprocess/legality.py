from __future__ import annotations

from .base import ClaimCandidate, PostprocessPolicy, RejectedClaim


def enforce_legality(
    *,
    candidates: tuple[ClaimCandidate, ...],
    policy: PostprocessPolicy,
) -> tuple[tuple[ClaimCandidate, ...], list[RejectedClaim]]:
    surviving: list[ClaimCandidate] = []
    rejected: list[RejectedClaim] = []
    for candidate in candidates:
        if not policy.emits_business_claims:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="business_claims_not_allowed",
                    message="Extractor lane is not allowed to emit business claims.",
                )
            )
            continue
        if policy.allowed_claim_families and candidate.claim_family not in policy.allowed_claim_families:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="unsupported_claim_family",
                    message=f"Claim family {candidate.claim_family!r} is not allowed.",
                )
            )
            continue
        if policy.allowed_field_paths and candidate.target_field_path not in policy.allowed_field_paths:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="illegal_field_path",
                    message=f"Field path {candidate.target_field_path!r} is not allowed.",
                )
            )
            continue
        # Enforce basic field/path consistency to prevent cross-slot drift.
        if not (
            candidate.target_field_path == candidate.target_field
            or candidate.target_field_path.startswith(candidate.target_field + ".")
            or candidate.target_field_path.startswith(candidate.target_field + "[")
        ):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="field_path_mismatch",
                    message=(
                        f"target_field {candidate.target_field!r} does not align with "
                        f"target_field_path {candidate.target_field_path!r}."
                    ),
                )
            )
            continue
        if policy.require_evidence_refs and not candidate.evidence_span_ids:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="missing_evidence_refs",
                    message="Claim is missing evidence references.",
                )
            )
            continue
        if candidate.candidate_value in (None, ""):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="unsupported_value",
                    message="Claim candidate value is empty.",
                )
            )
            continue
        surviving.append(candidate)
    return tuple(surviving), rejected
