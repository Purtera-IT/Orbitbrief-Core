from __future__ import annotations

import json
from pathlib import Path

from orbitbrief_core.compiler.core.load_contracts import PackContractPaths
from orbitbrief_core.compiler.packs.professional_services_text.compiler_runner import (
    compile_pack,
    emit_compiled_pack,
    load_compiled_pack,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _build_paths(tmp_path: Path) -> PackContractPaths:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps(
            {
                "version": "1.0.0",
                "narrative_modalities": {"txt": {}, "docx": {}},
                "source_contracts": {"bundle": "base"},
            }
        ),
    )
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps(
            {
                "version": "1.0.0",
                "pre_field_definitions": {
                    "project_summary": {"kind": "string"},
                    "site_count": {"kind": "integer"},
                },
                "post_field_definitions": {"scope_overview": {"kind": "string"}},
                "field_paths": ["project_summary", "site_count", "scope_overview"],
            }
        ),
    )
    enhanced_machine = _write(
        tmp_path / "professional_services_text_enhanced_machine.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "task_contract:",
                "  task_name: text_narrative_parser",
                "scope:",
                "  pack_id: professional_services_text",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
                "field_semantics:",
                "  project_summary:",
                "    desc: Summary field",
                "claim_family_semantics:",
                "  project_summary_claim:",
                "    desc: Summary claim family",
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    trigger_type: weak_evidence",
                "    machine_instruction: Ask for stronger support.",
                "    fields: [project_summary]",
                "    claim_families: [project_summary_claim]",
                "projection_rules:",
                "  summarize:",
                "    claim_family: project_summary_claim",
                "    target_fields: [scope_overview]",
                "modality_profiles:",
                "  txt: {}",
                "  docx: {}",
            ]
        )
        + "\n",
    )
    rich_modalities = _write(
        tmp_path / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modalities:",
                "  txt: {}",
                "  docx: {}",
                "parser_sandwich:",
                "  layer_a_deterministic_pre_parser: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary, site_count, scope_overview]",
            ]
        )
        + "\n",
    )
    return PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
    )


def test_compile_runner_end_to_end(tmp_path: Path) -> None:
    _write(
        tmp_path / "professional_services_text_examples.yaml",
        "\n".join(
            [
                "schema_id: professional_services_text_examples.v1",
                "pack_id: professional_services_text",
                "supported_modalities: [txt, docx]",
                "retrieval_exemplars:",
                "  - text: Project summary confirms switch refresh scope.",
                "    category: project_summary",
                "    linked_field_paths: [project_summary]",
                "    linked_claim_families: [project_summary_claim]",
                "negative_examples:",
                "  - text: Thanks, sent from my iPhone.",
                "    category: signature",
                "    modalities: [txt]",
            ]
        )
        + "\n",
    )
    artifacts = compile_pack(_build_paths(tmp_path))

    assert artifacts.ir.manifest.pack_id == "professional_services_text"
    assert artifacts.ir.manifest.admitted_modalities
    assert len(artifacts.field_table.rows) > 0
    assert len(artifacts.claim_family_table.rows) > 0
    assert len(artifacts.review_rule_table.rows) > 0
    assert len(artifacts.projection_rule_table.rows) > 0
    assert len(artifacts.parser_profiles.rows) > 0
    assert len(artifacts.negative_examples.rows) > 0
    assert len(artifacts.retrieval_exemplars.rows) > 0


def test_emit_and_load_compiled_pack_includes_examples(tmp_path: Path) -> None:
    _write(
        tmp_path / "professional_services_text_examples.yaml",
        "\n".join(
            [
                "schema_id: professional_services_text_examples.v1",
                "pack_id: professional_services_text",
                "supported_modalities: [txt, docx]",
                "retrieval_exemplars:",
                "  - text: Site count is 14 stores in wave one.",
                "    category: site_count",
                "    linked_field_paths: [site_count]",
                "    linked_claim_families: [project_summary_claim]",
                "negative_examples:",
                "  - text: Please consider the environment before printing.",
                "    category: legal_disclaimer",
                "    modalities: [docx]",
            ]
        )
        + "\n",
    )
    artifacts = compile_pack(_build_paths(tmp_path))
    out_root = tmp_path / "compiled_artifacts"
    emit_compiled_pack(artifacts, out_root)
    loaded = load_compiled_pack("professional_services_text", compiled_root=out_root)

    artifact_map = loaded.manifest.artifacts
    assert "negative_examples" in artifact_map
    assert "retrieval_exemplars" in artifact_map
    assert "field_table" in artifact_map
    assert artifact_map["negative_examples"].filename == "negative_examples.json"
    assert artifact_map["retrieval_exemplars"].filename == "retrieval_exemplars.json"
    assert loaded.negative_examples["artifact_name"] == "negative_examples"
    assert loaded.retrieval_exemplars["artifact_name"] == "retrieval_exemplars"


def test_compile_pack_marks_strict_alignment_enforced(tmp_path: Path) -> None:
    artifacts = compile_pack(_build_paths(tmp_path), strict_mask_alignment=True)
    assert artifacts.strict_mask_alignment_enforced is True


def test_compile_pack_autodiscovers_scope_and_handoff(tmp_path: Path) -> None:
    machine_dir = tmp_path / "base" / "machine"
    source_dir = tmp_path / "base" / "source"
    boundary_dir = tmp_path / "base" / "boundary_hardening"
    machine_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    boundary_dir.mkdir(parents=True, exist_ok=True)

    source_contracts = _write(
        source_dir / "managed_services_base_source_contracts.json",
        json.dumps({"version": "1.0.0", "narrative_modalities": {"txt": {}}, "source_contracts": {"bundle": "base"}}),
    )
    field_catalog = _write(
        source_dir / "managed_services_base_precise_field_catalog.json",
        json.dumps({"version": "1.0.0", "pre_field_definitions": {"project_summary": {"kind": "string"}}}),
    )
    enhanced_machine = _write(
        machine_dir / "professional_services_text_enhanced_machine.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "task_contract:",
                "  task_name: text_narrative_parser",
                "field_semantics:",
                "  project_summary:",
                "    desc: Summary field",
                "claim_family_semantics:",
                "  project_summary_claim:",
                "    desc: Summary claim family",
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    trigger_type: weak_evidence",
                "    machine_instruction: Ask for stronger support.",
                "    fields: [project_summary]",
                "    claim_families: [project_summary_claim]",
                "modality_profiles:",
                "  txt: {}",
            ]
        )
        + "\n",
    )
    rich_modalities = _write(
        machine_dir / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modalities:",
                "  txt: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary]",
            ]
        )
        + "\n",
    )
    _write(
        boundary_dir / "professional_services_text_scope_block.yaml",
        "\n".join(
            [
                "scope:",
                "  pack_id: professional_services_text",
                "  artifact_family: managed_services_text",
                "  role_id: transcript_or_notes",
            ]
        )
        + "\n",
    )
    _write(
        boundary_dir / "professional_services_text_handoff_contract.yaml",
        "\n".join(
            [
                "routing_handoff_contract:",
                "  candidate_domain_overlays: []",
                "  follow_on_artifact_requests: []",
                "  authority_needed_flags: []",
                "  verification_needed_flags: []",
                "  cross_pack_entities: []",
            ]
        )
        + "\n",
    )
    paths = PackContractPaths(
        pack_id="professional_services_text",
        source_contracts_path=source_contracts,
        field_catalog_path=field_catalog,
        enhanced_machine_path=enhanced_machine,
        rich_modalities_path=rich_modalities,
        scope_contract_path=None,
        handoff_contract_path=None,
    )
    artifacts = compile_pack(paths)
    input_paths = {path.name for path in artifacts.contract_input_paths}
    assert "professional_services_text_scope_block.yaml" in input_paths
    assert "professional_services_text_handoff_contract.yaml" in input_paths
