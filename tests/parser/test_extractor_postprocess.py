from __future__ import annotations

from orbitbrief_core.runtime_spine.extractors.postprocess import postprocess_extractor_output
from orbitbrief_core.runtime_spine.extractors.registry import ExtractorSpec
from orbitbrief_core.runtime_spine.postprocess import PostprocessPolicy


def _spec(*, kind: str, emits_business_claims: bool) -> ExtractorSpec:
    return ExtractorSpec(
        extractor_id=f"{kind}_spec",
        role_id="transcript_or_notes",
        kind=kind,
        entrypoint="orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor",
        supports_modalities=("txt",),
        supports_discourse_types=("meeting_notes",),
        packet_profile="p1",
        emits_business_claims=emits_business_claims,
        enabled=True,
    )


def test_postprocess_dedupes_and_drops_invalid_claims() -> None:
    output = {
        "field_claims": [
            {
                "claim_family": "scope_included_claim",
                "target_field": "scope_included",
                "target_field_path": "scope_included",
                "candidate_value": "scope_packet:1",
                "confidence": 0.8,
                "evidence_span_ids": ["span_1"],
            },
            {
                "claim_family": "scope_included_claim",
                "target_field": "scope_included",
                "target_field_path": "scope_included",
                "candidate_value": "scope_packet:1",
                "confidence": 0.75,
                "evidence_span_ids": ["span_2"],
            },
            {
                "claim_family": "not_real_family",
                "target_field": "x",
                "target_field_path": "x",
                "candidate_value": "bad",
                "confidence": 0.2,
                "evidence_span_ids": ["span_3"],
            },
            {"bad": "shape"},
        ]
    }
    result = postprocess_extractor_output(
        extractor_spec=_spec(kind="narrative", emits_business_claims=True),
        extraction_output=output,
        policy=PostprocessPolicy(
            emits_business_claims=True,
            allowed_claim_families=frozenset({"scope_included_claim"}),
            allowed_field_paths=frozenset({"scope_included"}),
            require_evidence_refs=True,
        ),
    )
    summary = result["summary"]
    assert summary["claims_emitted_count"] == 1
    assert summary["deduped_claims_count"] == 1
    assert summary["dropped_invalid_claims_count"] == 1


def test_postprocess_blocks_claims_for_intake_only() -> None:
    output = {
        "field_claims": [
            {
                "claim_family": "scope_included_claim",
                "target_field": "scope_included",
                "target_field_path": "scope_included",
                "candidate_value": "scope_packet:1",
                "confidence": 0.8,
                "evidence_span_ids": ["span_1"],
            }
        ]
    }
    result = postprocess_extractor_output(
        extractor_spec=_spec(kind="intake_only", emits_business_claims=False),
        extraction_output=output,
        policy=PostprocessPolicy(
            emits_business_claims=False,
            allowed_claim_families=frozenset(),
            allowed_field_paths=frozenset(),
            require_evidence_refs=True,
        ),
    )
    summary = result["summary"]
    assert summary["status"] == "claims_blocked_by_policy"
    assert summary["blocked_claims_count"] == 1
    assert summary["claims_emitted_count"] == 0
    assert result["normalized_output"]["field_claims"] == []


def test_postprocess_rejects_field_path_mismatch() -> None:
    output = {
        "field_claims": [
            {
                "claim_family": "scope_included_claim",
                "target_field": "scope_included",
                "target_field_path": "deliverables_required",
                "candidate_value": "scope_packet:1",
                "confidence": 0.8,
                "evidence_span_ids": ["span_1"],
            }
        ]
    }
    result = postprocess_extractor_output(
        extractor_spec=_spec(kind="narrative", emits_business_claims=True),
        extraction_output=output,
        policy=PostprocessPolicy(
            emits_business_claims=True,
            allowed_claim_families=frozenset({"scope_included_claim"}),
            allowed_field_paths=frozenset({"deliverables_required"}),
            require_evidence_refs=True,
        ),
    )
    summary = result["summary"]
    assert summary["claims_emitted_count"] == 0
    reason_codes = {row["reason_code"] for row in result["rejected_claims"]}
    assert "field_path_mismatch" in reason_codes
