from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, CanonicalParserProfile, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import resolve_precedence
from orbitbrief_core.compiler.packs.professional_services_text.compile_allowed_masks import (
    compile_allowed_masks,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_claim_family_table import (
    compile_claim_family_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_field_table import (
    compile_field_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_parser_profile_table import (
    compile_parser_profile_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_projection_rule_table import (
    compile_projection_rule_table,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_review_rule_table import (
    compile_review_rule_table,
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
                "fields": {"project_summary": {}, "scope_overview": {}, "timeline_summary": {}},
                "pre_field_definitions": {"project_summary": {"kind": "string", "desc": "summary"}},
                "post_field_definitions": {
                    "scope_overview": {"kind": "string", "desc": "overview"},
                    "timeline_summary": {"kind": "string", "desc": "timeline"},
                },
                "field_paths": ["project_summary", "scope_overview", "timeline_summary"],
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
                "    group: project",
                "    desc: Summary claim family",
                "    maps_to: [scope_overview]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    trigger_type: weak_evidence",
                "    machine_instruction: Ask for clearer support before extraction.",
                "    fields: [scope_overview]",
                "    claim_families: [project_summary_claim]",
                "projection_rules:",
                "  summarize_direct:",
                "    claim_family: project_summary_claim",
                "    target_fields: [scope_overview]",
                "    projection_mode: direct",
                "    notes: primary map",
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
                "modality_profiles:",
                "  txt: {}",
                "  docx: {}",
                "field_path_index:",
                "  rich_discovery_pre: [project_summary, scope_overview, timeline_summary]",
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


def _build_ir(tmp_path: Path) -> CanonicalIR:
    resolved = resolve_precedence(load_raw_contracts(_build_paths(tmp_path)))
    return build_canonical_ir(resolved)


def _compile_masks(tmp_path: Path):
    ir = _build_ir(tmp_path)
    field_table = compile_field_table(ir)
    claim_table = compile_claim_family_table(ir)
    review_table = compile_review_rule_table(ir)
    projection_table = compile_projection_rule_table(ir)
    masks = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    return ir, masks


def test_compile_parser_profile_table_happy_path(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    compiled = compile_parser_profile_table(ir, masks)
    assert compiled.rows
    assert compiled.by_parser_profile_id
    assert compiled.by_modality


def test_compile_parser_profile_table_invalid_modality_detection(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    first_id = next(iter(ir.parser_profiles.keys()))
    first = ir.parser_profiles[first_id]
    bad_profile = CanonicalParserProfile(
        parser_profile_id=first.parser_profile_id,
        modality="bad_modality",
        artifact_family=first.artifact_family,
        role_id=first.role_id,
        parser_kind=first.parser_kind,
        structure_preservation_mode=first.structure_preservation_mode,
        chronology_sensitive=first.chronology_sensitive,
        actor_sensitive=first.actor_sensitive,
        confidence_policy=first.confidence_policy,
        allowed_field_ids=first.allowed_field_ids,
        allowed_claim_family_ids=first.allowed_claim_family_ids,
        linked_review_rule_ids=first.linked_review_rule_ids,
        source_paths=first.source_paths,
        source_hashes=first.source_hashes,
        fallback_used=first.fallback_used,
    )
    parser_profiles = dict(ir.parser_profiles)
    parser_profiles[first_id] = bad_profile
    bad_ir = replace(ir, parser_profiles=MappingProxyType(parser_profiles))
    with pytest.raises(ContractLoadError, match="non-admitted modality"):
        compile_parser_profile_table(bad_ir, masks)


def test_compile_parser_profile_table_invalid_linked_field_claim_rule_detection(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    first_id = next(iter(ir.parser_profiles.keys()))
    first = ir.parser_profiles[first_id]
    bad_profile = replace(
        first,
        allowed_field_ids=("field:unknown:missing",),
        allowed_claim_family_ids=("claim:unknown:missing",),
        linked_review_rule_ids=("rule:unknown:missing",),
    )
    parser_profiles = dict(ir.parser_profiles)
    parser_profiles[first_id] = bad_profile
    bad_ir = replace(ir, parser_profiles=MappingProxyType(parser_profiles))
    with pytest.raises(ContractLoadError, match="unknown allowed_field_ids"):
        compile_parser_profile_table(bad_ir, masks)


def test_compile_parser_profile_table_alignment_with_allowed_mask(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    docx_mask_id = masks.by_modality["docx"]
    docx_mask = masks.by_mask_id[docx_mask_id]
    narrowed = replace(
        docx_mask,
        allowed_field_ids=(),
        allowed_claim_family_ids=(),
        allowed_review_rule_ids=(),
        denied_field_ids=tuple(sorted(set(docx_mask.denied_field_ids) | set(docx_mask.allowed_field_ids))),
        denied_claim_family_ids=tuple(sorted(set(docx_mask.denied_claim_family_ids) | set(docx_mask.allowed_claim_family_ids))),
        denied_review_rule_ids=tuple(sorted(set(docx_mask.denied_review_rule_ids) | set(docx_mask.allowed_review_rule_ids))),
    )
    custom_masks = replace(
        masks,
        masks=tuple(narrowed if m.mask_id == docx_mask_id else m for m in masks.masks),
        by_mask_id=MappingProxyType(
            {m.mask_id: (narrowed if m.mask_id == docx_mask_id else m) for m in masks.masks}
        ),
    )
    with pytest.raises(ContractLoadError, match="disallowed by mask"):
        compile_parser_profile_table(ir, custom_masks)


def test_compile_parser_profile_table_correct_indexes(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    compiled = compile_parser_profile_table(ir, masks)
    row = compiled.rows[0]
    assert compiled.by_parser_profile_id[row.parser_profile_id] == row
    assert compiled.by_modality[row.modality] == row.parser_profile_id
    assert row.parser_profile_id in compiled.by_parser_kind[row.parser_kind]
    assert row.parser_profile_id in compiled.by_confidence_policy[row.confidence_policy]
    assert row.parser_profile_id in compiled.by_runtime_class[row.runtime_class]


def test_compile_parser_profile_table_summary_counts(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    compiled = compile_parser_profile_table(ir, masks)
    summary = compiled.summary
    assert summary.total_parser_profiles == len(compiled.rows)
    assert set(summary.parser_profiles_by_modality.keys()) == set(ir.manifest.admitted_modalities)


def test_compile_parser_profile_table_diagnostics_generation(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    first_id = next(iter(ir.parser_profiles.keys()))
    first = ir.parser_profiles[first_id]
    noisy = replace(
        first,
        parser_kind="generic",
        confidence_policy="default",
        allowed_field_ids=(),
        allowed_claim_family_ids=(),
        linked_review_rule_ids=(),
        fallback_used=True,
    )
    parser_profiles = dict(ir.parser_profiles)
    parser_profiles[first_id] = noisy
    noisy_ir = replace(ir, parser_profiles=MappingProxyType(parser_profiles))
    compiled = compile_parser_profile_table(noisy_ir, masks)
    codes = {diag.code for diag in compiled.diagnostics if diag.parser_profile_id == first_id}
    assert "parser_profile_table.field_set_empty" in codes
    assert "parser_profile_table.claim_set_empty" in codes
    assert "parser_profile_table.rule_set_empty" in codes
    assert "parser_profile_table.fallback_used" in codes
    assert "parser_profile_table.parser_kind_generic" in codes
    assert "parser_profile_table.confidence_policy_generic" in codes


def test_compile_parser_profile_table_deterministic_row_ordering(tmp_path: Path) -> None:
    ir, masks = _compile_masks(tmp_path)
    one = compile_parser_profile_table(ir, masks)
    two = compile_parser_profile_table(ir, masks)
    assert tuple(row.parser_profile_id for row in one.rows) == tuple(row.parser_profile_id for row in two.rows)

