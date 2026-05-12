from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.runtime_spine.compiled_pack_runtime import load_compiled_pack_runtime_policy
from orbitbrief_core.runtime_spine.extractors.narrative_extractor import run_narrative_extractor


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict
    claim_family_table: dict
    field_table: dict
    projection_rules: dict
    review_rules: dict
    retrieval_exemplars: dict
    negative_examples: dict


def _packet(*, family: str, packet_id: str = "packet:1", span_id: str = "span:1") -> dict:
    return {
        "packet_id": packet_id,
        "primary_span_id": span_id,
        "span_ids": [span_id],
        "confidence": 0.82,
        "metadata": {"packet_family": family, "uncertainty_markers": []},
    }


def test_compiled_projection_rules_override_default_projector_mapping() -> None:
    compiled_pack = _CompiledPackStub(
        manifest=_ManifestStub(),
        parser_profiles={"rows": []},
        claim_family_table={"rows": [{"claim_family_id": "claim:pack:risk_claim", "name": "risk_claim"}]},
        field_table={"rows": [{"field_id": "field:pack:risk_custom", "field_path": "custom.risk"}]},
        projection_rules={
            "rows": [
                {
                    "projection_rule_id": "projection:1",
                    "source_claim_family_id": "claim:pack:risk_claim",
                    "target_field_ids": ["field:pack:risk_custom"],
                }
            ]
        },
        review_rules={"rows": []},
        retrieval_exemplars={"rows": []},
        negative_examples={"rows": []},
    )
    policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="txt",
        packet_candidates=[_packet(family="risk_packet")],
        compiled_runtime_policy=policy,
    )
    assert result["field_claims"]
    assert result["field_claims"][0]["field_path"] == "custom.risk"


def test_negative_examples_only_add_support_review_flags_not_new_claim_paths() -> None:
    claim_body = "risk:anchor=span:1 supports=0"
    compiled_pack = _CompiledPackStub(
        manifest=_ManifestStub(),
        parser_profiles={"rows": []},
        claim_family_table={"rows": [{"claim_family_id": "claim:pack:risk_claim", "name": "risk_claim"}]},
        field_table={"rows": [{"field_id": "field:pack:risk", "field_path": "risks"}]},
        projection_rules={"rows": []},
        review_rules={"rows": []},
        retrieval_exemplars={
            "rows": [
                {
                    "exemplar_id": "ex:1",
                    "text": "risk evidence example",
                    "linked_claim_family_ids": ["claim:pack:risk_claim"],
                    "modalities": ["txt"],
                    "discourse_profiles": ["meeting_notes"],
                    "weight": 1.0,
                }
            ]
        },
        negative_examples={
            "rows": [
                {
                    "negative_example_id": "neg:1",
                    "text": claim_body,
                    "linked_claim_family_ids": ["claim:pack:risk_claim"],
                    "modalities": ["txt"],
                    "discourse_profiles": ["meeting_notes"],
                    "severity": "high",
                }
            ]
        },
    )
    policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="txt",
        packet_candidates=[_packet(family="risk_packet")],
        compiled_runtime_policy=policy,
    )
    assert "negative_example_overlap" in result["review_flags"]
    assert result["field_claims"][0]["field_path"] == "risks"
    assert any(item["code"] == "negative_example_overlap" for item in result["extraction_diagnostics"])
