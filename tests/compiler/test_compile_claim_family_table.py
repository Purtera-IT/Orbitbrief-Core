from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import resolve_precedence
from orbitbrief_core.compiler.packs.professional_services_text.compile_claim_family_table import (
    compile_claim_family_table,
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
                "    evidence_patterns: [summary, overview]",
                "    negative_patterns: [none]",
                "    maps_to: [project_summary]",
                "review_rules:",
                "  weak_signal:",
                "    severity: warning",
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


def test_compile_claim_family_table_happy_path(tmp_path: Path) -> None:
    compiled = compile_claim_family_table(_build_ir(tmp_path))
    assert compiled.rows
    assert compiled.by_claim_family_id
    assert compiled.by_name


def test_compile_claim_family_table_duplicate_claim_family_id_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    values = list(ir.claim_families.values())
    assert len(values) >= 1
    first = values[0]
    dup = replace(first, name=f"{first.name}:dup")
    claim_families = dict(ir.claim_families)
    claim_families[f"{first.claim_family_id}:dup"] = replace(dup, claim_family_id=first.claim_family_id)
    bad_ir = replace(ir, claim_families=MappingProxyType(claim_families))
    with pytest.raises(ContractLoadError, match="Duplicate claim_family_id"):
        compile_claim_family_table(bad_ir)


def test_compile_claim_family_table_duplicate_claim_family_name_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    values = list(ir.claim_families.values())
    first = values[0]
    dup = replace(first, claim_family_id=f"{first.claim_family_id}:dup")
    claim_families = dict(ir.claim_families)
    claim_families[dup.claim_family_id] = dup
    bad_ir = replace(ir, claim_families=MappingProxyType(claim_families))
    with pytest.raises(ContractLoadError, match="Duplicate claim family name"):
        compile_claim_family_table(bad_ir)


def test_compile_claim_family_table_invalid_projection_target_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.claim_families.keys()))
    first = ir.claim_families[first_id]
    bad_claim = replace(first, projection_target_field_ids=("field:unknown:missing",))
    claim_families = dict(ir.claim_families)
    claim_families[first_id] = bad_claim
    bad_ir = replace(ir, claim_families=MappingProxyType(claim_families))
    with pytest.raises(ContractLoadError, match="unknown projection target field IDs"):
        compile_claim_family_table(bad_ir)


def test_compile_claim_family_table_invalid_review_rule_link_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.claim_families.keys()))
    first = ir.claim_families[first_id]
    bad_claim = replace(first, linked_review_rule_ids=("rule:unknown:missing",))
    claim_families = dict(ir.claim_families)
    claim_families[first_id] = bad_claim
    bad_ir = replace(ir, claim_families=MappingProxyType(claim_families))
    with pytest.raises(ContractLoadError, match="unknown linked review rule IDs"):
        compile_claim_family_table(bad_ir)


def test_compile_claim_family_table_correct_indexes(tmp_path: Path) -> None:
    compiled = compile_claim_family_table(_build_ir(tmp_path))
    row = compiled.rows[0]
    assert compiled.by_claim_family_id[row.claim_family_id] == row
    assert compiled.by_name[row.name] == row.claim_family_id
    assert row.claim_family_id in compiled.by_group[row.group]
    assert row.claim_family_id in compiled.by_runtime_class[row.runtime_class]
    for field_id in row.projection_target_field_ids:
        assert row.claim_family_id in compiled.by_projection_target_field_id[field_id]


def test_compile_claim_family_table_summary_counts(tmp_path: Path) -> None:
    compiled = compile_claim_family_table(_build_ir(tmp_path))
    summary = compiled.summary
    assert summary.total_claim_families == len(compiled.rows)
    assert summary.fallback_used_claim_family_count == len(summary.claim_families_using_fallback_semantics)


def test_compile_claim_family_table_diagnostics_generation(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.claim_families.keys()))
    first = ir.claim_families[first_id]
    noisy = replace(
        first,
        machine_gloss="",
        human_definition="",
        evidence_patterns=(),
        negative_patterns=(),
        projection_target_field_ids=(),
        linked_review_rule_ids=(),
        fallback_used=True,
        group="default",
    )
    claim_families = dict(ir.claim_families)
    claim_families[first_id] = noisy
    noisy_ir = replace(ir, claim_families=MappingProxyType(claim_families))
    compiled = compile_claim_family_table(noisy_ir)
    codes = {diag.code for diag in compiled.diagnostics if diag.claim_family_id == first_id}
    assert "claim_family_table.machine_gloss_missing" in codes
    assert "claim_family_table.semantic_definition_missing" in codes
    assert "claim_family_table.projection_targets_missing" in codes
    assert "claim_family_table.review_rule_links_missing" in codes
    assert "claim_family_table.evidence_patterns_missing" in codes
    assert "claim_family_table.negative_patterns_missing" in codes
    assert "claim_family_table.fallback_used" in codes
    assert "claim_family_table.group_too_generic" in codes


def test_compile_claim_family_table_deterministic_row_ordering(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    one = compile_claim_family_table(ir)
    two = compile_claim_family_table(ir)
    assert tuple(row.claim_family_id for row in one.rows) == tuple(row.claim_family_id for row in two.rows)
