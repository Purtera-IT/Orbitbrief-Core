from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import resolve_precedence
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


def _build_ir(tmp_path: Path) -> CanonicalIR:
    resolved = resolve_precedence(load_raw_contracts(_build_paths(tmp_path)))
    return build_canonical_ir(resolved)


def test_compile_review_rule_table_happy_path(tmp_path: Path) -> None:
    compiled = compile_review_rule_table(_build_ir(tmp_path))
    assert compiled.rows
    assert compiled.by_rule_id
    assert compiled.by_name


def test_compile_review_rule_table_duplicate_rule_id_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first = next(iter(ir.review_rules.values()))
    dup = replace(first, name=f"{first.name}:dup")
    review_rules = dict(ir.review_rules)
    review_rules[f"{first.rule_id}:dup"] = replace(dup, rule_id=first.rule_id)
    bad_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    with pytest.raises(ContractLoadError, match="Duplicate rule_id"):
        compile_review_rule_table(bad_ir)


def test_compile_review_rule_table_duplicate_rule_name_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first = next(iter(ir.review_rules.values()))
    dup = replace(first, rule_id=f"{first.rule_id}:dup")
    review_rules = dict(ir.review_rules)
    review_rules[dup.rule_id] = dup
    bad_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    with pytest.raises(ContractLoadError, match="Duplicate rule name"):
        compile_review_rule_table(bad_ir)


def test_compile_review_rule_table_invalid_field_target_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.review_rules.keys()))
    first = ir.review_rules[first_id]
    bad = replace(first, applies_to_field_ids=("field:unknown:missing",))
    review_rules = dict(ir.review_rules)
    review_rules[first_id] = bad
    bad_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    with pytest.raises(ContractLoadError, match="unknown applies_to_field_ids"):
        compile_review_rule_table(bad_ir)


def test_compile_review_rule_table_invalid_claim_target_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.review_rules.keys()))
    first = ir.review_rules[first_id]
    bad = replace(first, applies_to_claim_family_ids=("claim:unknown:missing",))
    review_rules = dict(ir.review_rules)
    review_rules[first_id] = bad
    bad_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    with pytest.raises(ContractLoadError, match="unknown applies_to_claim_family_ids"):
        compile_review_rule_table(bad_ir)


def test_compile_review_rule_table_invalid_modality_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.review_rules.keys()))
    first = ir.review_rules[first_id]
    bad = replace(first, applies_to_modalities=("txt", "bad_modality"))
    review_rules = dict(ir.review_rules)
    review_rules[first_id] = bad
    bad_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    with pytest.raises(ContractLoadError, match="non-admitted modalities"):
        compile_review_rule_table(bad_ir)


def test_compile_review_rule_table_correct_indexes(tmp_path: Path) -> None:
    compiled = compile_review_rule_table(_build_ir(tmp_path))
    row = compiled.rows[0]
    assert compiled.by_rule_id[row.rule_id] == row
    assert compiled.by_name[row.name] == row.rule_id
    assert row.rule_id in compiled.by_severity[row.severity]
    assert row.rule_id in compiled.by_trigger_type[row.trigger_type]
    assert row.rule_id in compiled.by_runtime_class[row.runtime_class]
    for field_id in row.applies_to_field_ids:
        assert row.rule_id in compiled.by_field_target_id[field_id]
    for claim_id in row.applies_to_claim_family_ids:
        assert row.rule_id in compiled.by_claim_target_id[claim_id]
    for modality in row.applies_to_modalities:
        assert row.rule_id in compiled.by_modality[modality]


def test_compile_review_rule_table_summary_counts(tmp_path: Path) -> None:
    compiled = compile_review_rule_table(_build_ir(tmp_path))
    summary = compiled.summary
    assert summary.total_review_rules == len(compiled.rows)
    assert summary.fallback_used_rule_count == len(summary.rules_using_fallback_semantics)


def test_compile_review_rule_table_diagnostics_generation(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.review_rules.keys()))
    first = ir.review_rules[first_id]
    noisy = replace(
        first,
        machine_instruction="",
        applies_to_field_ids=(),
        applies_to_claim_family_ids=(),
        applies_to_modalities=(),
        fallback_used=True,
        severity="unknown",
        trigger_type="rule",
    )
    review_rules = dict(ir.review_rules)
    review_rules[first_id] = noisy
    noisy_ir = replace(ir, review_rules=MappingProxyType(review_rules))
    compiled = compile_review_rule_table(noisy_ir)
    codes = {diag.code for diag in compiled.diagnostics if diag.rule_id == first_id}
    assert "review_rule_table.machine_instruction_missing" in codes
    assert "review_rule_table.field_targets_missing" in codes
    assert "review_rule_table.claim_targets_missing" in codes
    assert "review_rule_table.modality_targets_missing" in codes
    assert "review_rule_table.targets_missing_all" in codes
    assert "review_rule_table.fallback_used" in codes
    assert "review_rule_table.severity_generic" in codes
    assert "review_rule_table.trigger_type_generic" in codes


def test_compile_review_rule_table_deterministic_row_ordering(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    one = compile_review_rule_table(ir)
    two = compile_review_rule_table(ir)
    assert tuple(row.rule_id for row in one.rows) == tuple(row.rule_id for row in two.rows)
