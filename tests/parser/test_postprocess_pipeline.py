from __future__ import annotations

from orbitbrief_core.runtime_spine.postprocess import (
    ClaimCandidate,
    ExtractorOutput,
    PostprocessPolicy,
    run_postprocess,
)


def test_postprocess_groups_contradictions_and_flags_review() -> None:
    output = ExtractorOutput(
        candidates=(
            ClaimCandidate(
                claim_id="c1",
                claim_family="scope_included_claim",
                target_field="scope_included",
                target_field_path="scope_included",
                candidate_value="Install APs",
                confidence=0.6,
                evidence_span_ids=("span_1",),
            ),
            ClaimCandidate(
                claim_id="c2",
                claim_family="scope_included_claim",
                target_field="scope_included",
                target_field_path="scope_included",
                candidate_value="Install switches",
                confidence=0.52,
                evidence_span_ids=("span_2",),
            ),
        )
    )
    policy = PostprocessPolicy(
        emits_business_claims=True,
        allowed_claim_families=frozenset({"scope_included_claim"}),
        require_evidence_refs=True,
    )
    result = run_postprocess(extractor_output=output, policy=policy)
    assert len(result.surviving_claims) == 2
    assert len(result.contradiction_groups) == 1
    assert any(flag.code == "conflicting_evidence" for flag in result.review_flags)
