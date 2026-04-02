from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, CanonicalProjectionRule
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError


@dataclass(frozen=True)
class CompiledProjectionRuleRow:
    projection_rule_id: str
    source_claim_family_id: str
    target_field_ids: tuple[str, ...]
    projection_mode: str
    notes: str | None
    fallback_used: bool
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    semantic_source_kind: str
    runtime_class: str
    target_density: int
    has_notes: bool
    has_targets: bool
    is_multi_target: bool


@dataclass(frozen=True)
class ProjectionRuleTableDiagnostic:
    level: str
    code: str
    message: str
    projection_rule_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectionRuleTableSummary:
    total_projection_rules: int
    projection_rules_by_mode: Mapping[str, int]
    projection_rules_by_runtime_class: Mapping[str, int]
    projection_rules_without_targets: tuple[str, ...]
    projection_rules_with_multiple_targets: tuple[str, ...]
    projection_rules_missing_notes: tuple[str, ...]
    projection_rules_using_fallback_semantics: tuple[str, ...]
    fallback_used_projection_rule_count: int


@dataclass(frozen=True)
class CompiledProjectionRuleTable:
    rows: tuple[CompiledProjectionRuleRow, ...]
    by_projection_rule_id: Mapping[str, CompiledProjectionRuleRow]
    by_source_claim_family_id: Mapping[str, tuple[str, ...]]
    by_target_field_id: Mapping[str, tuple[str, ...]]
    by_projection_mode: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[ProjectionRuleTableDiagnostic, ...]
    summary: ProjectionRuleTableSummary


def _validate_uniqueness(ir: CanonicalIR) -> None:
    rule_ids = [spec.projection_rule_id for spec in ir.projection_rules.values()]
    if len(set(rule_ids)) != len(rule_ids):
        raise ContractLoadError("Duplicate projection_rule_id detected in CanonicalIR.projection_rules")


def _validate_projection_rule_spec(
    rule: CanonicalProjectionRule,
    claim_ids: set[str],
    field_ids: set[str],
) -> None:
    if not rule.projection_rule_id:
        raise ContractLoadError("Projection rule must have non-empty projection_rule_id")
    if not rule.source_claim_family_id:
        raise ContractLoadError(f"Projection rule {rule.projection_rule_id} must have non-empty source_claim_family_id")
    if rule.source_claim_family_id not in claim_ids:
        raise ContractLoadError(
            f"Projection rule {rule.projection_rule_id} references unknown source claim family ID: "
            f"{rule.source_claim_family_id}"
        )
    unknown_target_ids = sorted(set(rule.target_field_ids) - field_ids)
    if unknown_target_ids:
        raise ContractLoadError(
            f"Projection rule {rule.projection_rule_id} references unknown target field IDs: {unknown_target_ids}"
        )
    if not rule.source_paths or not rule.source_hashes:
        raise ContractLoadError(f"Projection rule {rule.projection_rule_id} is missing provenance paths/hashes")
    if len(rule.source_paths) != len(rule.source_hashes):
        raise ContractLoadError(
            f"Projection rule {rule.projection_rule_id} has mismatched provenance tuple lengths "
            f"(paths={len(rule.source_paths)}, hashes={len(rule.source_hashes)})"
        )


def _semantic_source_kind(rule: CanonicalProjectionRule, has_targets: bool) -> str:
    if rule.fallback_used:
        return "fallback"
    if has_targets:
        return "primary"
    return "unknown"


def _runtime_class(target_count: int) -> str:
    if target_count == 0:
        return "empty_projection"
    if target_count == 1:
        return "single_target_projection"
    return "multi_target_projection"


def _flatten_projection_rule_spec_to_row(
    rule: CanonicalProjectionRule,
    claim_ids: set[str],
    field_ids: set[str],
) -> CompiledProjectionRuleRow:
    _validate_projection_rule_spec(rule, claim_ids, field_ids)

    target_field_ids = tuple(sorted(set(rule.target_field_ids)))
    source_paths = tuple(sorted(rule.source_paths))
    source_hashes = tuple(sorted(rule.source_hashes))
    projection_mode = " ".join(rule.projection_mode.split())
    notes = " ".join(rule.notes.split()) if isinstance(rule.notes, str) else None

    has_targets = bool(target_field_ids)
    has_notes = bool(notes)
    target_density = len(target_field_ids)

    return CompiledProjectionRuleRow(
        projection_rule_id=rule.projection_rule_id,
        source_claim_family_id=rule.source_claim_family_id,
        target_field_ids=target_field_ids,
        projection_mode=projection_mode,
        notes=notes,
        fallback_used=rule.fallback_used,
        authoritative_source_role="enhanced_machine",
        source_paths=source_paths,
        source_hashes=source_hashes,
        semantic_source_kind=_semantic_source_kind(rule, has_targets),
        runtime_class=_runtime_class(target_density),
        target_density=target_density,
        has_notes=has_notes,
        has_targets=has_targets,
        is_multi_target=target_density > 1,
    )


def _build_projection_rule_id_index(rows: tuple[CompiledProjectionRuleRow, ...]) -> Mapping[str, CompiledProjectionRuleRow]:
    return MappingProxyType({row.projection_rule_id: row for row in rows})


def _build_source_claim_index(rows: tuple[CompiledProjectionRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.source_claim_family_id].append(row.projection_rule_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_target_field_index(rows: tuple[CompiledProjectionRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for target_field_id in row.target_field_ids:
            buckets[target_field_id].append(row.projection_rule_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_projection_mode_index(rows: tuple[CompiledProjectionRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.projection_mode].append(row.projection_rule_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_runtime_class_index(rows: tuple[CompiledProjectionRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.runtime_class].append(row.projection_rule_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_diagnostics(rows: tuple[CompiledProjectionRuleRow, ...]) -> tuple[ProjectionRuleTableDiagnostic, ...]:
    diagnostics: list[ProjectionRuleTableDiagnostic] = []
    for row in rows:
        if not row.has_targets:
            diagnostics.append(
                ProjectionRuleTableDiagnostic(
                    level="warning",
                    code="projection_rule_table.targets_missing",
                    message="Projection rule has no target field IDs",
                    projection_rule_id=row.projection_rule_id,
                )
            )
        if not row.has_notes:
            diagnostics.append(
                ProjectionRuleTableDiagnostic(
                    level="warning",
                    code="projection_rule_table.notes_missing",
                    message="Projection rule notes are empty",
                    projection_rule_id=row.projection_rule_id,
                )
            )
        if row.is_multi_target:
            diagnostics.append(
                ProjectionRuleTableDiagnostic(
                    level="warning",
                    code="projection_rule_table.multi_target_projection",
                    message="Projection rule has multiple target fields and may need stricter runtime handling",
                    projection_rule_id=row.projection_rule_id,
                    context={"target_density": row.target_density},
                )
            )
        if row.fallback_used:
            diagnostics.append(
                ProjectionRuleTableDiagnostic(
                    level="info",
                    code="projection_rule_table.fallback_used",
                    message="Projection rule uses fallback-derived semantics",
                    projection_rule_id=row.projection_rule_id,
                )
            )
        if row.projection_mode.strip().lower() in {"", "generic", "unknown", "rule", "default"}:
            diagnostics.append(
                ProjectionRuleTableDiagnostic(
                    level="warning",
                    code="projection_rule_table.projection_mode_generic",
                    message="Projection mode is generic and may need hardening",
                    projection_rule_id=row.projection_rule_id,
                    context={"projection_mode": row.projection_mode},
                )
            )
    return tuple(diagnostics)


def _build_summary(rows: tuple[CompiledProjectionRuleRow, ...]) -> ProjectionRuleTableSummary:
    by_mode: dict[str, int] = defaultdict(int)
    by_runtime_class: dict[str, int] = defaultdict(int)
    without_targets: list[str] = []
    with_multiple_targets: list[str] = []
    missing_notes: list[str] = []
    using_fallback: list[str] = []

    for row in rows:
        by_mode[row.projection_mode] += 1
        by_runtime_class[row.runtime_class] += 1
        if not row.has_targets:
            without_targets.append(row.projection_rule_id)
        if row.is_multi_target:
            with_multiple_targets.append(row.projection_rule_id)
        if not row.has_notes:
            missing_notes.append(row.projection_rule_id)
        if row.fallback_used:
            using_fallback.append(row.projection_rule_id)

    return ProjectionRuleTableSummary(
        total_projection_rules=len(rows),
        projection_rules_by_mode=MappingProxyType(dict(sorted(by_mode.items()))),
        projection_rules_by_runtime_class=MappingProxyType(dict(sorted(by_runtime_class.items()))),
        projection_rules_without_targets=tuple(sorted(without_targets)),
        projection_rules_with_multiple_targets=tuple(sorted(with_multiple_targets)),
        projection_rules_missing_notes=tuple(sorted(missing_notes)),
        projection_rules_using_fallback_semantics=tuple(sorted(using_fallback)),
        fallback_used_projection_rule_count=len(using_fallback),
    )


def to_jsonable_row(row: CompiledProjectionRuleRow) -> dict[str, Any]:
    return {
        "projection_rule_id": row.projection_rule_id,
        "source_claim_family_id": row.source_claim_family_id,
        "target_field_ids": list(row.target_field_ids),
        "projection_mode": row.projection_mode,
        "notes": row.notes,
        "fallback_used": row.fallback_used,
        "authoritative_source_role": row.authoritative_source_role,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "semantic_source_kind": row.semantic_source_kind,
        "runtime_class": row.runtime_class,
        "target_density": row.target_density,
        "has_notes": row.has_notes,
        "has_targets": row.has_targets,
        "is_multi_target": row.is_multi_target,
    }


def to_jsonable_summary(summary: ProjectionRuleTableSummary) -> dict[str, Any]:
    return {
        "total_projection_rules": summary.total_projection_rules,
        "projection_rules_by_mode": dict(summary.projection_rules_by_mode),
        "projection_rules_by_runtime_class": dict(summary.projection_rules_by_runtime_class),
        "projection_rules_without_targets": list(summary.projection_rules_without_targets),
        "projection_rules_with_multiple_targets": list(summary.projection_rules_with_multiple_targets),
        "projection_rules_missing_notes": list(summary.projection_rules_missing_notes),
        "projection_rules_using_fallback_semantics": list(summary.projection_rules_using_fallback_semantics),
        "fallback_used_projection_rule_count": summary.fallback_used_projection_rule_count,
    }


def to_jsonable_diagnostic(diag: ProjectionRuleTableDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "projection_rule_id": diag.projection_rule_id,
        "context": dict(diag.context),
    }


def compile_projection_rule_table(ir: CanonicalIR) -> CompiledProjectionRuleTable:
    _validate_uniqueness(ir)
    claim_ids = set(ir.claim_families.keys())
    field_ids = set(ir.fields.keys())

    rows = tuple(
        sorted(
            (
                _flatten_projection_rule_spec_to_row(
                    rule=rule,
                    claim_ids=claim_ids,
                    field_ids=field_ids,
                )
                for rule in ir.projection_rules.values()
            ),
            key=lambda row: row.projection_rule_id,
        )
    )
    diagnostics = _build_diagnostics(rows)
    summary = _build_summary(rows)

    return CompiledProjectionRuleTable(
        rows=rows,
        by_projection_rule_id=_build_projection_rule_id_index(rows),
        by_source_claim_family_id=_build_source_claim_index(rows),
        by_target_field_id=_build_target_field_index(rows),
        by_projection_mode=_build_projection_mode_index(rows),
        by_runtime_class=_build_runtime_class_index(rows),
        diagnostics=diagnostics,
        summary=summary,
    )
