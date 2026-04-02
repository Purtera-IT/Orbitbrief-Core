from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError, PackContractPaths, load_raw_contracts
from orbitbrief_core.compiler.core.resolve_precedence import resolve_precedence
from orbitbrief_core.compiler.packs.professional_services_text.compile_field_table import (
    compile_field_table,
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


def _build_ir(tmp_path: Path) -> CanonicalIR:
    resolved = resolve_precedence(load_raw_contracts(_build_paths(tmp_path)))
    return build_canonical_ir(resolved)


def test_compile_field_table_happy_path(tmp_path: Path) -> None:
    compiled = compile_field_table(_build_ir(tmp_path))
    assert compiled.rows
    assert compiled.by_field_id
    assert compiled.by_field_path


def test_compile_field_table_duplicate_field_path_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first = next(iter(ir.fields.values()))
    dup = replace(first, field_id=f"{first.field_id}:dup")
    fields = dict(ir.fields)
    fields[dup.field_id] = dup
    bad_ir = replace(ir, fields=MappingProxyType(fields))
    with pytest.raises(ContractLoadError, match="Duplicate field_path"):
        compile_field_table(bad_ir)


def test_compile_field_table_invalid_modality_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.fields.keys()))
    first = ir.fields[first_id]
    bad_field = replace(first, allowed_modalities=("txt", "not_admitted"))
    fields = dict(ir.fields)
    fields[first_id] = bad_field
    bad_ir = replace(ir, fields=MappingProxyType(fields))
    with pytest.raises(ContractLoadError, match="non-admitted modalities"):
        compile_field_table(bad_ir)


def test_compile_field_table_invalid_pre_or_post_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.fields.keys()))
    first = ir.fields[first_id]
    bad_field = replace(first, pre_or_post="middle")
    fields = dict(ir.fields)
    fields[first_id] = bad_field
    bad_ir = replace(ir, fields=MappingProxyType(fields))
    with pytest.raises(ContractLoadError, match="invalid pre_or_post"):
        compile_field_table(bad_ir)


def test_compile_field_table_correct_indexes(tmp_path: Path) -> None:
    compiled = compile_field_table(_build_ir(tmp_path))
    row = compiled.rows[0]
    assert compiled.by_field_id[row.field_id] == row
    assert compiled.by_field_path[row.field_path] == row.field_id
    assert row.field_id in compiled.by_group[row.group]
    assert row.field_id in compiled.by_pre_or_post[row.pre_or_post]
    for modality in row.allowed_modalities:
        assert row.field_id in compiled.by_modality[modality]


def test_compile_field_table_summary_counts(tmp_path: Path) -> None:
    compiled = compile_field_table(_build_ir(tmp_path))
    summary = compiled.summary
    assert summary.total_fields == len(compiled.rows)
    assert summary.pre_fields + summary.post_fields == summary.total_fields
    assert summary.repeatable_fields + summary.scalar_fields == summary.total_fields
    assert summary.fallback_used_fields_count == len(summary.fields_using_fallback_semantics)


def test_compile_field_table_diagnostics_generation(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.fields.keys()))
    first = ir.fields[first_id]
    noisy = replace(
        first,
        machine_gloss="",
        human_definition="",
        linked_claim_family_ids=(),
        linked_review_rule_ids=(),
        linked_projection_rule_ids=(),
        fallback_used=True,
    )
    fields = dict(ir.fields)
    fields[first_id] = noisy
    noisy_ir = replace(ir, fields=MappingProxyType(fields))
    compiled = compile_field_table(noisy_ir)
    codes = {diag.code for diag in compiled.diagnostics if diag.field_id == first_id}
    assert "field_table.machine_gloss_missing" in codes
    assert "field_table.semantic_definition_missing" in codes
    assert "field_table.claim_links_missing" in codes
    assert "field_table.rule_links_missing" in codes
    assert "field_table.projection_links_missing" in codes
    assert "field_table.fallback_used" in codes
    assert "field_table.machine_gloss_missing" in codes
    assert "field_table.semantic_text_missing" in codes


def test_compile_field_table_deterministic_row_ordering(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    one = compile_field_table(ir)
    two = compile_field_table(ir)
    assert tuple(row.field_id for row in one.rows) == tuple(row.field_id for row in two.rows)


def test_compile_field_table_runtime_columns_populated(tmp_path: Path) -> None:
    compiled = compile_field_table(_build_ir(tmp_path))
    row = compiled.rows[0]
    assert row.semantic_source_kind in {"primary", "fallback", "legal_only"}
    assert row.runtime_class in {"scalar_pre", "scalar_post", "list_pre", "list_post"}
    assert isinstance(row.linkage_density, int)
    assert row.has_human_definition in {True, False}
    assert row.has_machine_gloss in {True, False}


def test_compile_field_table_provenance_length_mismatch_detection(tmp_path: Path) -> None:
    ir = _build_ir(tmp_path)
    first_id = next(iter(ir.fields.keys()))
    first = ir.fields[first_id]
    bad_field = replace(first, source_paths=("one-path",), source_hashes=("h1", "h2"))
    fields = dict(ir.fields)
    fields[first_id] = bad_field
    bad_ir = replace(ir, fields=MappingProxyType(fields))
    with pytest.raises(ContractLoadError, match="mismatched provenance tuple lengths"):
        compile_field_table(bad_ir)
