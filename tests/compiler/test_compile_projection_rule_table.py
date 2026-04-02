from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import resolve_precedence
from orbitbrief_core.compiler.packs.professional_services_text.compile_projection_rule_table import (
    compile_projection_rule_table,
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
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
                "    trigger_type: weak_evidence",
                "    machine_instruction: Ask for clearer support before extraction.",
                "    fields: [project_summary]",
                "    claim_families: [project_summary_claim]",
                "projection_rules:",
                "  summarize_direct:",
                "    claim_family: project_summary_claim",
                "    target_fields: [scope_overview]",
                "    projection_mode: direct",
                "    notes: primary map",
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


def test_compile_projection_rule_table_happy_path(tmp_path: Path) -> None:
    compiled = compile_projection_rule_table(_build_ir(tmp_path))
    assert compiled.rows
    assert compiled.by_projection_rule_id
    assert compiled.by_source_claim_family_id


def test_compile_projection_rule_table_duplicate_projection_rule_id_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first = next(iter(ir.projection_rules.values()))
    dup = replace(first, projection_mode="derived")
    projection_rules = dict(ir.projection_rules)
    projection_rules[f"{first.projection_rule_id}:dup"] = replace(dup, projection_rule_id=first.projection_rule_id)
    bad_ir = replace(ir, projection_rules=MappingProxyType(projection_rules))
    with pytest.raises(ContractLoadError, match="Duplicate projection_rule_id"):
        compile_projection_rule_table(bad_ir)


def test_compile_projection_rule_table_invalid_source_claim_family_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.projection_rules.keys()))
    first = ir.projection_rules[first_id]
    bad = replace(first, source_claim_family_id="claim:unknown:missing")
    projection_rules = dict(ir.projection_rules)
    projection_rules[first_id] = bad
    bad_ir = replace(ir, projection_rules=MappingProxyType(projection_rules))
    with pytest.raises(ContractLoadError, match="unknown source claim family ID"):
        compile_projection_rule_table(bad_ir)


def test_compile_projection_rule_table_invalid_target_field_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.projection_rules.keys()))
    first = ir.projection_rules[first_id]
    bad = replace(first, target_field_ids=("field:unknown:missing",))
    projection_rules = dict(ir.projection_rules)
    projection_rules[first_id] = bad
    bad_ir = replace(ir, projection_rules=MappingProxyType(projection_rules))
    with pytest.raises(ContractLoadError, match="unknown target field IDs"):
        compile_projection_rule_table(bad_ir)


def test_compile_projection_rule_table_correct_indexes(tmp_path: Path) -> None:
    compiled = compile_projection_rule_table(_build_ir(tmp_path))
    row = compiled.rows[0]
    assert compiled.by_projection_rule_id[row.projection_rule_id] == row
    assert row.projection_rule_id in compiled.by_source_claim_family_id[row.source_claim_family_id]
    assert row.projection_rule_id in compiled.by_projection_mode[row.projection_mode]
    assert row.projection_rule_id in compiled.by_runtime_class[row.runtime_class]
    for target_id in row.target_field_ids:
        assert row.projection_rule_id in compiled.by_target_field_id[target_id]


def test_compile_projection_rule_table_summary_counts(tmp_path: Path) -> None:
    compiled = compile_projection_rule_table(_build_ir(tmp_path))
    summary = compiled.summary
    assert summary.total_projection_rules == len(compiled.rows)
    assert summary.fallback_used_projection_rule_count == len(summary.projection_rules_using_fallback_semantics)


def test_compile_projection_rule_table_diagnostics_generation(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.projection_rules.keys()))
    first = ir.projection_rules[first_id]
    noisy = replace(
        first,
        target_field_ids=(),
        notes=None,
        projection_mode="generic",
        fallback_used=True,
    )
    projection_rules = dict(ir.projection_rules)
    projection_rules[first_id] = noisy
    noisy_ir = replace(ir, projection_rules=MappingProxyType(projection_rules))
    compiled = compile_projection_rule_table(noisy_ir)
    codes = {diag.code for diag in compiled.diagnostics if diag.projection_rule_id == first_id}
    assert "projection_rule_table.targets_missing" in codes
    assert "projection_rule_table.notes_missing" in codes
    assert "projection_rule_table.fallback_used" in codes
    assert "projection_rule_table.projection_mode_generic" in codes


def test_compile_projection_rule_table_deterministic_row_ordering(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first = next(iter(ir.projection_rules.values()))
    projection_rules = dict(ir.projection_rules)
    projection_rules[f"{first.projection_rule_id}:b"] = replace(
        first,
        projection_rule_id=f"{first.projection_rule_id}:b",
        projection_mode="derived",
        notes="secondary map",
    )
    ir_two = replace(ir, projection_rules=MappingProxyType(projection_rules))
    one = compile_projection_rule_table(ir_two)
    two = compile_projection_rule_table(ir_two)
    assert tuple(row.projection_rule_id for row in one.rows) == tuple(row.projection_rule_id for row in two.rows)

