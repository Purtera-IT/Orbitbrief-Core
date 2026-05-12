from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.runtime_spine.compiled_pack_runtime import load_compiled_pack_runtime_policy
from orbitbrief_core.runtime_spine.extractors.registry import ExtractorSpec
from orbitbrief_core.runtime_spine.pipeline import _build_postprocess_policy


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    parser_profiles: dict
    claim_family_table: dict
    field_table: dict
    projection_rule_table: dict
    review_rule_table: dict


def test_compiled_pack_runtime_policy_loads_normalized_tables() -> None:
    compiled_pack = _CompiledPackStub(
        parser_profiles={"rows": [{"modality": "pdf_text", "parser_profile_id": "parser:pdf"}]},
        claim_family_table={"rows": [{"claim_family_name": "risk_claim"}]},
        field_table={"rows": [{"field_path": "risks"}]},
        projection_rule_table={"rows": [{"claim_family": "risk_claim", "field_path": "risks"}]},
        review_rule_table={"rows": [{"rule_key": "verification_confidence_threshold", "rule_value": 0.61}]},
    )
    policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
    assert policy.parser_profile_by_modality["pdf_text"] == "parser:pdf"
    assert "risk_claim" in policy.allowed_claim_families
    assert "risks" in policy.allowed_field_paths
    assert policy.projection_targets_for_claim_family("risk_claim") == ("risks",)
    assert policy.review_rules["verification_confidence_threshold"] == 0.61
    assert policy.consumption_audit["projection_rule_rows"] == 1


def test_postprocess_policy_consumes_compiled_runtime_policy_when_extractor_is_sparse() -> None:
    compiled_pack = _CompiledPackStub(
        parser_profiles={"rows": []},
        claim_family_table={"rows": [{"claim_family_name": "risk_claim"}]},
        field_table={"rows": [{"field_path": "risks"}]},
        projection_rule_table={"rows": []},
        review_rule_table={"rows": [{"rule_key": "stronger_source_confidence_threshold", "rule_value": 0.48}]},
    )
    runtime_policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
    spec = ExtractorSpec(
        extractor_id="x",
        role_id="transcript_or_notes",
        kind="narrative",
        entrypoint="orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor",
        supports_modalities=("pdf_text",),
        supports_discourse_types=("memo",),
        packet_profile="default",
        emits_business_claims=True,
        enabled=True,
        allowed_claim_families=(),
        allowed_field_paths=(),
        require_evidence_refs=True,
        review_rules={},
    )
    postprocess = _build_postprocess_policy(extractor_spec=spec, runtime_policy=runtime_policy)
    assert "risk_claim" in postprocess.allowed_claim_families
    assert "risks" in postprocess.allowed_field_paths
    assert postprocess.review_rules.get("stronger_source_confidence_threshold") == 0.48



def test_postprocess_policy_prefers_compiled_projection_targets_over_sparse_registry_paths() -> None:
    compiled_pack = _CompiledPackStub(
        parser_profiles={"rows": []},
        claim_family_table={
            "rows": [
                {
                    "claim_family_name": "risk_claim",
                    "projection_target_field_ids": [
                        "field:pack:risks",
                        "field:pack:risks_or_dependencies",
                    ],
                }
            ]
        },
        field_table={
            "rows": [
                {"field_id": "field:pack:risks", "field_path": "risks[]"},
                {"field_id": "field:pack:risks_or_dependencies", "field_path": "risks_or_dependencies[]"},
            ]
        },
        projection_rule_table={"rows": []},
        review_rule_table={"rows": []},
    )
    runtime_policy = load_compiled_pack_runtime_policy(compiled_pack=compiled_pack)
    spec = ExtractorSpec(
        extractor_id="x",
        role_id="transcript_or_notes",
        kind="narrative",
        entrypoint="orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor",
        supports_modalities=("pdf_text",),
        supports_discourse_types=("memo",),
        packet_profile="default",
        emits_business_claims=True,
        enabled=True,
        allowed_claim_families=("risk_claim",),
        allowed_field_paths=("risks",),
        require_evidence_refs=True,
        review_rules={},
    )
    postprocess = _build_postprocess_policy(extractor_spec=spec, runtime_policy=runtime_policy)
    assert postprocess.allowed_field_paths == frozenset({"risks[]", "risks_or_dependencies[]"})
