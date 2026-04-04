from __future__ import annotations

from pathlib import Path

from orbitbrief_core.runtime_spine.compat.legacy_output_adapter import adapt_parse_extraction_result
from orbitbrief_core.parser.runtime import ParseExtractionResult, ParseRuntimeResult
from orbitbrief_core.parser.router import DiscourseType, ParsePlan
from orbitbrief_core.parser.shared.types import ContainerType, DocumentParse, SourceLayer


def _minimal_runtime_result() -> ParseExtractionResult:
    parse_plan = ParsePlan(
        doc_id="doc_1",
        container_type=ContainerType.TEXT,
        discourse_type=DiscourseType.MEETING_NOTES,
        parser_profile_id="parser:professional_services_text:txt",
        adapter_chain=("txt",),
        strategy_chain=("meeting_notes",),
        quality_mode="balanced",
        authority_mode="default",
        packet_policy="default",
        routing_confidence=0.92,
        route_scores=(),
        route_evidence=(),
        metadata={"modality": "txt"},
    )
    document_parse = DocumentParse(
        doc_id="doc_1",
        pack_id="professional_services_text",
        role_id="transcript_or_notes",
        modality="txt",
        container_type=ContainerType.TEXT,
        discourse_type=DiscourseType.MEETING_NOTES,
        source_layer=SourceLayer.NORMALIZED,
    )
    runtime = ParseRuntimeResult(
        parse_plan=parse_plan,
        document_parse=document_parse,
        packet_candidates=(),
        diagnostics=(),
    )
    return ParseExtractionResult(
        parse_runtime_result=runtime,
        extractor_id="narrative_v1",
        extractor_kind="narrative",
        emits_business_claims=True,
        extraction_result={"field_claims": []},
        postprocess_result={
            "normalized_output": {
                "field_claims": [
                    {
                        "claim_id": "claim:1",
                        "claim_family": "scope_included_claim",
                        "target_field": "scope_included",
                        "target_field_path": "scope_included",
                        "candidate_value": "scope_packet:1",
                        "confidence": 0.8,
                        "evidence_span_ids": ["span_1"],
                    }
                ]
            },
            "review_flags": [],
        },
        pipeline_state="extract",
        reason_codes=(),
        review_required=False,
        diagnostics=(),
    )


def test_legacy_output_adapter_uses_normalized_postprocess_claims(tmp_path: Path) -> None:
    artifact = tmp_path / "meeting.txt"
    artifact.write_text("scope", encoding="utf-8")
    envelope = adapt_parse_extraction_result(_minimal_runtime_result(), artifact_path=artifact)
    claims = envelope["planner_output"].canonical_pre_draft["claims"]
    assert len(claims) == 1
    assert claims[0]["claim_id"] == "claim:1"


def test_stale_runtime_modules_import_cleanly() -> None:
    import orbitbrief_core.runtime_spine.coverage as coverage
    from orbitbrief_core.runtime_spine.extractors.base import ExtractionResult
    from orbitbrief_core.runtime_spine.extractors.intake_only import intake_only_result

    plan = coverage.build_field_support_plan()
    assert isinstance(plan, dict)
    assert plan.get("roles")
    result = intake_only_result("transcript_or_notes", "txt", parsed=None, reason="fallback")
    assert isinstance(result, ExtractionResult)
    assert result.field_claims == []
    assert result.review_flags and result.review_flags[0]["code"] == "intake_only_lane"
