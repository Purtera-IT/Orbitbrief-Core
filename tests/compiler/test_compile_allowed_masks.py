from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, CanonicalReviewRule, build_canonical_ir
from orbitbrief_core.compiler.core.load_contracts import PackContractPaths, load_raw_contracts
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


def _compile_all(tmp_path: Path):
    ir = _build_ir(tmp_path)
    field_table = compile_field_table(ir)
    claim_table = compile_claim_family_table(ir)
    review_table = compile_review_rule_table(ir)
    projection_table = compile_projection_rule_table(ir)
    return ir, field_table, claim_table, review_table, projection_table


def test_compile_allowed_masks_happy_path(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    compiled = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    assert compiled.masks
    assert compiled.by_mask_id
    assert compiled.by_modality


def test_compile_allowed_masks_one_mask_per_admitted_modality(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    compiled = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    assert len(compiled.masks) == len(ir.manifest.admitted_modalities)
    assert set(compiled.by_modality.keys()) == set(ir.manifest.admitted_modalities)


def test_compile_allowed_masks_projection_rule_filtering_when_target_field_denied(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    rows = list(field_table.rows)
    scope_row = next(row for row in rows if row.field_path == "scope_overview")
    idx = rows.index(scope_row)
    rows[idx] = replace(scope_row, allowed_modalities=("txt",))
    custom_field_table = replace(
        field_table,
        rows=tuple(rows),
        by_field_id=MappingProxyType({row.field_id: row for row in rows}),
        by_modality=MappingProxyType({"txt": tuple(sorted({*field_table.by_modality.get("txt", ()), scope_row.field_id}))}),
    )
    compiled = compile_allowed_masks(ir, custom_field_table, claim_table, review_table, projection_table)
    docx_mask = compiled.by_mask_id[compiled.by_modality["docx"]]
    assert not docx_mask.allowed_projection_rule_ids


def test_compile_allowed_masks_claim_family_filtering_when_no_targets(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    rows = list(claim_table.rows)
    first = rows[0]
    rows[0] = replace(first, projection_target_field_ids=())
    custom_claim_table = replace(
        claim_table,
        rows=tuple(rows),
        by_claim_family_id=MappingProxyType({row.claim_family_id: row for row in rows}),
    )
    compiled = compile_allowed_masks(ir, field_table, custom_claim_table, review_table, projection_table)
    for mask in compiled.masks:
        assert first.claim_family_id not in mask.allowed_claim_family_ids


def test_compile_allowed_masks_review_rule_filtering_for_field_claim_modality_global(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    _, rule = next(iter(ir.review_rules.items()))
    modality_rule = CanonicalReviewRule(
        rule_id=f"{rule.rule_id}:modality",
        name=f"{rule.name}:modality",
        severity="warning",
        trigger_type="modality",
        machine_instruction="Modality-specific safety rule",
        applies_to_field_ids=(),
        applies_to_claim_family_ids=(),
        applies_to_modalities=("docx",),
        source_paths=rule.source_paths,
        source_hashes=rule.source_hashes,
        fallback_used=rule.fallback_used,
    )
    global_rule = CanonicalReviewRule(
        rule_id=f"{rule.rule_id}:global",
        name=f"{rule.name}:global",
        severity="warning",
        trigger_type="global",
        machine_instruction="Global safety rule",
        applies_to_field_ids=(),
        applies_to_claim_family_ids=(),
        applies_to_modalities=(),
        source_paths=rule.source_paths,
        source_hashes=rule.source_hashes,
        fallback_used=rule.fallback_used,
    )
    review_rules = dict(ir.review_rules)
    review_rules[modality_rule.rule_id] = modality_rule
    review_rules[global_rule.rule_id] = global_rule
    ir_with_global = replace(ir, review_rules=MappingProxyType(review_rules))
    custom_review_table = compile_review_rule_table(ir_with_global)
    compiled = compile_allowed_masks(ir_with_global, field_table, claim_table, custom_review_table, projection_table)
    txt_mask = compiled.by_mask_id[compiled.by_modality["txt"]]
    docx_mask = compiled.by_mask_id[compiled.by_modality["docx"]]
    baseline_rule_id = next(iter(ir.review_rules.keys()))
    assert baseline_rule_id in txt_mask.allowed_review_rule_ids
    assert baseline_rule_id in docx_mask.allowed_review_rule_ids
    assert modality_rule.rule_id not in txt_mask.allowed_review_rule_ids
    assert modality_rule.rule_id in docx_mask.allowed_review_rule_ids
    for mask in compiled.masks:
        assert global_rule.rule_id in mask.allowed_review_rule_ids


def test_compile_allowed_masks_denied_sets_correctness(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    compiled = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    all_fields = set(field_table.by_field_id.keys())
    all_claims = set(claim_table.by_claim_family_id.keys())
    all_rules = set(review_table.by_rule_id.keys())
    all_projections = set(projection_table.by_projection_rule_id.keys())
    for mask in compiled.masks:
        assert set(mask.allowed_field_ids).isdisjoint(mask.denied_field_ids)
        assert set(mask.allowed_claim_family_ids).isdisjoint(mask.denied_claim_family_ids)
        assert set(mask.allowed_review_rule_ids).isdisjoint(mask.denied_review_rule_ids)
        assert set(mask.allowed_projection_rule_ids).isdisjoint(mask.denied_projection_rule_ids)
        assert set(mask.allowed_field_ids) | set(mask.denied_field_ids) == all_fields
        assert set(mask.allowed_claim_family_ids) | set(mask.denied_claim_family_ids) == all_claims
        assert set(mask.allowed_review_rule_ids) | set(mask.denied_review_rule_ids) == all_rules
        assert set(mask.allowed_projection_rule_ids) | set(mask.denied_projection_rule_ids) == all_projections


def test_compile_allowed_masks_deterministic_ordering(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    one = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    two = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    assert tuple(mask.mask_id for mask in one.masks) == tuple(mask.mask_id for mask in two.masks)


def test_compile_allowed_masks_summary_counts(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    compiled = compile_allowed_masks(ir, field_table, claim_table, review_table, projection_table)
    summary = compiled.summary
    assert summary.total_masks == len(compiled.masks)
    assert set(summary.masks_by_modality.keys()) == set(ir.manifest.admitted_modalities)


def test_compile_allowed_masks_diagnostics_generation(tmp_path: Path) -> None:
    ir, field_table, claim_table, review_table, projection_table = _compile_all(tmp_path)
    rows = [replace(row, allowed_modalities=("txt",) if row.allowed_modalities else ()) for row in field_table.rows]
    custom_field_table = replace(
        field_table,
        rows=tuple(rows),
        by_field_id=MappingProxyType({row.field_id: row for row in rows}),
        by_modality=MappingProxyType(
            {
                "txt": tuple(sorted({rid for row in rows for rid in [row.field_id] if "txt" in row.allowed_modalities})),
            }
        ),
    )
    compiled = compile_allowed_masks(ir, custom_field_table, claim_table, review_table, projection_table)
    docx_mask = compiled.by_mask_id[compiled.by_modality["docx"]]
    codes = {diag.code for diag in compiled.diagnostics if diag.mask_id == docx_mask.mask_id}
    assert "allowed_masks.claim_families_empty" in codes
    assert "allowed_masks.projection_rules_empty" in codes

