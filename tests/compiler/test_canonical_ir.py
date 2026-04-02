from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orbitbrief_core.compiler.core.canonical_ir import build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import ResolvedContractsBundle, resolve_precedence


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _build_paths(tmp_path: Path) -> PackContractPaths:
    source_contracts = _write(
        tmp_path / "managed_services_base_source_contracts.json",
        json.dumps(
            {
                "version": "1.0.0",
                "modalities": {"txt": {}, "docx": {}},
                "sources": {"bundle": "base"},
            }
        ),
    )
    field_catalog = _write(
        tmp_path / "managed_services_base_precise_field_catalog.json",
        json.dumps(
            {
                "version": "1.0.0",
                "fields": {"project_summary": {}, "scope_overview": {}},
                "pre_field_definitions": {"project_summary": {"kind": "string", "desc": "summary"}},
                "post_field_definitions": {"scope_overview": {"kind": "string", "desc": "overview"}},
                "field_paths": ["project_summary", "scope_overview"],
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
                "  primary_outputs: [scope_overview]",
                "field_semantics:",
                "  project_summary:",
                "    desc: Summary field",
                "claim_family_semantics:",
                "  project_summary_claim:",
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    fields: [project_summary]",
                "projection_rules:",
                "  summarize:",
                "    claim_family: project_summary_claim",
                "    target_fields: [scope_overview]",
                "modality_profiles:",
                "  txt: {}",
            ]
        )
        + "\n",
    )
    rich_modalities = _write(
        tmp_path / "professional_services_text_rich_all_modalities.yaml",
        "\n".join(
            [
                "version: 1.0.0",
                "modality_profiles:",
                "  txt: {}",
                "  docx: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary, scope_overview]",
                "parser_sandwich:",
                "  layer_a_deterministic_pre_parser: {}",
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


def _build_resolved(tmp_path: Path) -> ResolvedContractsBundle:
    return resolve_precedence(load_raw_contracts(_build_paths(tmp_path)))


def test_build_canonical_ir_success(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    ir = build_canonical_ir(resolved)
    assert ir.manifest.pack_id == "professional_services_text"
    assert ir.fields
    assert ir.parser_profiles


def test_no_canonical_field_for_illegal_semantic_only_field(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    altered = ResolvedContractsBundle(
        pack_id=resolved.pack_id,
        resolved_scope=resolved.resolved_scope,
        resolved_handoff=resolved.resolved_handoff,
        resolved_source_inventory=resolved.resolved_source_inventory,
        resolved_modalities=resolved.resolved_modalities,
        resolved_field_legality=resolved.resolved_field_legality,
        resolved_field_semantics={"project_summary": {}, "illegal_semantic_only_field": {}},
        resolved_claim_family_semantics=resolved.resolved_claim_family_semantics,
        resolved_parser_profiles=resolved.resolved_parser_profiles,
        resolved_review_rules=resolved.resolved_review_rules,
        resolved_projection_rules=resolved.resolved_projection_rules,
        resolved_semantic_sections=resolved.resolved_semantic_sections,
        resolved_structural_defaults=resolved.resolved_structural_defaults,
        resolution_records=resolved.resolution_records,
        diagnostics=resolved.diagnostics,
    )
    ir = build_canonical_ir(altered)
    assert all(spec.field_path != "illegal_semantic_only_field" for spec in ir.fields.values())


def test_stable_deterministic_ids(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    ir_one = build_canonical_ir(resolved)
    ir_two = build_canonical_ir(resolved)
    assert tuple(sorted(ir_one.fields.keys())) == tuple(sorted(ir_two.fields.keys()))


def test_manifest_uses_real_file_content_hashes(tmp_path: Path) -> None:
    paths = _build_paths(tmp_path)
    resolved = resolve_precedence(load_raw_contracts(paths))
    ir = build_canonical_ir(resolved)
    source_inventory_path = ir.manifest.source_paths["source_inventory"]
    expected_hash = hashlib.sha256(Path(source_inventory_path).read_bytes()).hexdigest()
    assert ir.manifest.source_hashes["source_inventory"] == expected_hash


def test_parser_profiles_only_for_admitted_modalities(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    ir = build_canonical_ir(resolved)
    admitted = set(resolved.resolved_modalities.keys())
    profile_modalities = {p.modality for p in ir.parser_profiles.values()}
    assert profile_modalities.issubset(admitted)


def test_field_objects_have_linked_relationships(tmp_path: Path) -> None:
    ir = build_canonical_ir(_build_resolved(tmp_path))
    project_summary = next(spec for spec in ir.fields.values() if spec.field_path == "project_summary")
    assert project_summary.linked_claim_family_ids
    assert project_summary.linked_review_rule_ids


def test_projection_rule_target_validation(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    altered = ResolvedContractsBundle(
        pack_id=resolved.pack_id,
        resolved_scope=resolved.resolved_scope,
        resolved_handoff=resolved.resolved_handoff,
        resolved_source_inventory=resolved.resolved_source_inventory,
        resolved_modalities=resolved.resolved_modalities,
        resolved_field_legality=resolved.resolved_field_legality,
        resolved_field_semantics=resolved.resolved_field_semantics,
        resolved_claim_family_semantics=resolved.resolved_claim_family_semantics,
        resolved_parser_profiles=resolved.resolved_parser_profiles,
        resolved_review_rules=resolved.resolved_review_rules,
        resolved_projection_rules={"bad_projection": {"claim_family": "project_summary_claim", "target_fields": ["not_legal"]}},
        resolved_semantic_sections=resolved.resolved_semantic_sections,
        resolved_structural_defaults=resolved.resolved_structural_defaults,
        resolution_records=resolved.resolution_records,
        diagnostics=resolved.diagnostics,
    )
    with pytest.raises(ContractLoadError, match="unknown target fields"):
        build_canonical_ir(altered)


def test_projection_rule_unknown_source_claim_family_validation(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    altered = ResolvedContractsBundle(
        pack_id=resolved.pack_id,
        resolved_scope=resolved.resolved_scope,
        resolved_handoff=resolved.resolved_handoff,
        resolved_source_inventory=resolved.resolved_source_inventory,
        resolved_modalities=resolved.resolved_modalities,
        resolved_field_legality=resolved.resolved_field_legality,
        resolved_field_semantics=resolved.resolved_field_semantics,
        resolved_claim_family_semantics=resolved.resolved_claim_family_semantics,
        resolved_parser_profiles=resolved.resolved_parser_profiles,
        resolved_review_rules=resolved.resolved_review_rules,
        resolved_projection_rules={"bad_projection": {"claim_family": "not_existing_claim", "target_fields": ["scope_overview"]}},
        resolved_semantic_sections=resolved.resolved_semantic_sections,
        resolved_structural_defaults=resolved.resolved_structural_defaults,
        resolution_records=resolved.resolution_records,
        diagnostics=resolved.diagnostics,
    )
    with pytest.raises(ContractLoadError, match="unknown source claim family"):
        build_canonical_ir(altered)


def test_parser_allowlists_can_be_modality_specific(tmp_path: Path) -> None:
    resolved = _build_resolved(tmp_path)
    altered = ResolvedContractsBundle(
        pack_id=resolved.pack_id,
        resolved_scope=resolved.resolved_scope,
        resolved_handoff=resolved.resolved_handoff,
        resolved_source_inventory=resolved.resolved_source_inventory,
        resolved_modalities=resolved.resolved_modalities,
        resolved_field_legality=resolved.resolved_field_legality,
        resolved_field_semantics=resolved.resolved_field_semantics,
        resolved_claim_family_semantics=resolved.resolved_claim_family_semantics,
        resolved_parser_profiles={
            "txt": {
                "allowed_field_paths": ["project_summary"],
                "allowed_claim_families": ["project_summary_claim"],
                "linked_review_rules": ["weak_signal"],
            },
            "docx": {},
        },
        resolved_review_rules=resolved.resolved_review_rules,
        resolved_projection_rules=resolved.resolved_projection_rules,
        resolved_semantic_sections=resolved.resolved_semantic_sections,
        resolved_structural_defaults=resolved.resolved_structural_defaults,
        resolution_records=resolved.resolution_records,
        diagnostics=resolved.diagnostics,
    )
    ir = build_canonical_ir(altered)
    txt_profile = next(profile for profile in ir.parser_profiles.values() if profile.modality == "txt")
    assert len(txt_profile.allowed_field_ids) == 1
    assert len(txt_profile.allowed_claim_family_ids) == 1
    assert len(txt_profile.linked_review_rule_ids) == 1


def test_edge_generation_sanity(tmp_path: Path) -> None:
    ir = build_canonical_ir(_build_resolved(tmp_path))
    assert ir.edges
    assert any(edge.edge_type == "modality_to_parser" for edge in ir.edges)


def test_routing_contract_remains_auxiliary(tmp_path: Path) -> None:
    ir = build_canonical_ir(_build_resolved(tmp_path))
    assert ir.routing is None
    assert all("candidate_domain_overlays" not in spec.field_path for spec in ir.fields.values())


def test_provenance_fields_populated(tmp_path: Path) -> None:
    ir = build_canonical_ir(_build_resolved(tmp_path))
    some_field = next(iter(ir.fields.values()))
    assert some_field.source_paths
    assert some_field.source_hashes
