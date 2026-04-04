from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    claim_id: str
    claim_family: str
    target_field: str
    target_field_path: str
    candidate_value: Any
    confidence: float
    evidence_span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProcessedClaim:
    claim_id: str
    claim_family: str
    target_field: str
    target_field_path: str
    normalized_value: Any
    confidence: float
    evidence_span_ids: tuple[str, ...]
    source_claim_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RejectedClaim:
    claim_id: str
    reason_code: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContradictionGroup:
    contradiction_id: str
    target_field_path: str
    claim_ids: tuple[str, ...]
    reason_code: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    flag_id: str
    code: str
    severity: str
    message: str
    claim_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractorOutput:
    candidates: tuple[ClaimCandidate, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PostprocessPolicy:
    emits_business_claims: bool
    allowed_claim_families: frozenset[str] = frozenset()
    allowed_field_paths: frozenset[str] = frozenset()
    require_evidence_refs: bool = True
    review_rules: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PostprocessResult:
    surviving_claims: tuple[ProcessedClaim, ...]
    rejected_claims: tuple[RejectedClaim, ...]
    contradiction_groups: tuple[ContradictionGroup, ...]
    review_flags: tuple[ReviewFlag, ...]
    audit: Mapping[str, Any] = field(default_factory=dict)


def run_postprocess(
    *,
    extractor_output: ExtractorOutput,
    policy: PostprocessPolicy,
) -> PostprocessResult:
    from .contradictions import group_contradictions
    from .dedupe import dedupe_claims
    from .legality import enforce_legality
    from .normalizers import normalize_claims
    from .review_flags import generate_review_flags

    legal_candidates, rejected_legality = enforce_legality(
        candidates=extractor_output.candidates,
        policy=policy,
    )
    normalized_claims = normalize_claims(legal_candidates)
    deduped_claims, dedupe_rejections = dedupe_claims(normalized_claims)
    contradiction_groups = group_contradictions(deduped_claims)
    flags = generate_review_flags(
        claims=deduped_claims,
        contradiction_groups=contradiction_groups,
        policy=policy,
    )
    rejected = tuple(rejected_legality + dedupe_rejections)
    return PostprocessResult(
        surviving_claims=deduped_claims,
        rejected_claims=rejected,
        contradiction_groups=contradiction_groups,
        review_flags=flags,
        audit={
            "input_claim_count": len(extractor_output.candidates),
            "surviving_claim_count": len(deduped_claims),
            "rejected_claim_count": len(rejected),
            "contradiction_group_count": len(contradiction_groups),
            "review_flag_count": len(flags),
        },
    )
