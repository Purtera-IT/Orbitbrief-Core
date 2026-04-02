from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, CanonicalReviewRule
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError


@dataclass(frozen=True)
class CompiledReviewRuleRow:
    rule_id: str
    name: str
    severity: str
    trigger_type: str
    machine_instruction: str
    applies_to_field_ids: tuple[str, ...]
    applies_to_claim_family_ids: tuple[str, ...]
    applies_to_modalities: tuple[str, ...]
    fallback_used: bool
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    semantic_source_kind: str
    runtime_class: str
    field_target_density: int
    claim_target_density: int
    modality_target_density: int
    total_target_density: int
    has_machine_instruction: bool
    has_field_targets: bool
    has_claim_targets: bool
    has_modality_targets: bool


@dataclass(frozen=True)
class ReviewRuleTableDiagnostic:
    level: str
    code: str
    message: str
    rule_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewRuleTableSummary:
    total_review_rules: int
    review_rules_by_severity: Mapping[str, int]
    review_rules_by_trigger_type: Mapping[str, int]
    review_rules_by_runtime_class: Mapping[str, int]
    review_rules_missing_machine_instruction: tuple[str, ...]
    review_rules_without_field_targets: tuple[str, ...]
    review_rules_without_claim_targets: tuple[str, ...]
    review_rules_without_modality_targets: tuple[str, ...]
    review_rules_without_any_targets: tuple[str, ...]
    fallback_used_rule_count: int
    rules_using_fallback_semantics: tuple[str, ...]


@dataclass(frozen=True)
class CompiledReviewRuleTable:
    rows: tuple[CompiledReviewRuleRow, ...]
    by_rule_id: Mapping[str, CompiledReviewRuleRow]
    by_name: Mapping[str, str]
    by_severity: Mapping[str, tuple[str, ...]]
    by_trigger_type: Mapping[str, tuple[str, ...]]
    by_field_target_id: Mapping[str, tuple[str, ...]]
    by_claim_target_id: Mapping[str, tuple[str, ...]]
    by_modality: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[ReviewRuleTableDiagnostic, ...]
    summary: ReviewRuleTableSummary


def _validate_uniqueness(ir: CanonicalIR) -> None:
    rule_ids = [rule.rule_id for rule in ir.review_rules.values()]
    names = [rule.name for rule in ir.review_rules.values()]
    if len(set(rule_ids)) != len(rule_ids):
        raise ContractLoadError("Duplicate rule_id detected in CanonicalIR.review_rules")
    if len(set(names)) != len(names):
        raise ContractLoadError("Duplicate rule name detected in CanonicalIR.review_rules")


def _validate_review_rule_spec(
    rule: CanonicalReviewRule,
    field_ids: set[str],
    claim_ids: set[str],
    admitted_modalities: set[str],
) -> None:
    if not rule.rule_id:
        raise ContractLoadError("Review rule must have non-empty rule_id")
    if not rule.name:
        raise ContractLoadError(f"Review rule {rule.rule_id} must have non-empty name")
    if not rule.severity:
        raise ContractLoadError(f"Review rule {rule.rule_id} must have non-empty severity")
    if not rule.trigger_type:
        raise ContractLoadError(f"Review rule {rule.rule_id} must have non-empty trigger_type")
    if not rule.source_paths or not rule.source_hashes:
        raise ContractLoadError(f"Review rule {rule.rule_id} is missing provenance paths/hashes")
    if len(rule.source_paths) != len(rule.source_hashes):
        raise ContractLoadError(
            f"Review rule {rule.rule_id} has mismatched provenance tuple lengths "
            f"(paths={len(rule.source_paths)}, hashes={len(rule.source_hashes)})"
        )
    unknown_fields = sorted(set(rule.applies_to_field_ids) - field_ids)
    if unknown_fields:
        raise ContractLoadError(
            f"Review rule {rule.rule_id} references unknown applies_to_field_ids: {unknown_fields}"
        )
    unknown_claims = sorted(set(rule.applies_to_claim_family_ids) - claim_ids)
    if unknown_claims:
        raise ContractLoadError(
            f"Review rule {rule.rule_id} references unknown applies_to_claim_family_ids: {unknown_claims}"
        )
    unknown_modalities = sorted(set(rule.applies_to_modalities) - admitted_modalities)
    if unknown_modalities:
        raise ContractLoadError(
            f"Review rule {rule.rule_id} references non-admitted modalities: {unknown_modalities}"
        )


def _semantic_source_kind(rule: CanonicalReviewRule, machine_instruction: str) -> str:
    if rule.fallback_used:
        return "fallback"
    if machine_instruction:
        return "primary"
    if rule.applies_to_field_ids or rule.applies_to_claim_family_ids or rule.applies_to_modalities:
        return "minimal"
    return "unknown"


def _runtime_class(has_field_targets: bool, has_claim_targets: bool, has_modality_targets: bool) -> str:
    if has_field_targets and has_claim_targets and has_modality_targets:
        return "hybrid_rule"
    if has_field_targets and has_claim_targets:
        return "field_claim_rule"
    if has_field_targets:
        return "field_rule"
    if has_claim_targets:
        return "claim_rule"
    if has_modality_targets:
        return "modality_rule"
    return "global_rule"


def _flatten_review_rule_spec_to_row(
    rule: CanonicalReviewRule,
    field_ids: set[str],
    claim_ids: set[str],
    admitted_modalities: set[str],
) -> CompiledReviewRuleRow:
    _validate_review_rule_spec(rule, field_ids, claim_ids, admitted_modalities)

    machine_instruction = " ".join(rule.machine_instruction.split())
    applies_to_field_ids = tuple(sorted(rule.applies_to_field_ids))
    applies_to_claim_family_ids = tuple(sorted(rule.applies_to_claim_family_ids))
    applies_to_modalities = tuple(sorted(rule.applies_to_modalities))
    source_paths = tuple(sorted(rule.source_paths))
    source_hashes = tuple(sorted(rule.source_hashes))

    has_machine_instruction = bool(machine_instruction)
    has_field_targets = bool(applies_to_field_ids)
    has_claim_targets = bool(applies_to_claim_family_ids)
    has_modality_targets = bool(applies_to_modalities)
    field_target_density = len(applies_to_field_ids)
    claim_target_density = len(applies_to_claim_family_ids)
    modality_target_density = len(applies_to_modalities)

    return CompiledReviewRuleRow(
        rule_id=rule.rule_id,
        name=rule.name,
        severity=rule.severity,
        trigger_type=rule.trigger_type,
        machine_instruction=machine_instruction,
        applies_to_field_ids=applies_to_field_ids,
        applies_to_claim_family_ids=applies_to_claim_family_ids,
        applies_to_modalities=applies_to_modalities,
        fallback_used=rule.fallback_used,
        authoritative_source_role="enhanced_machine",
        source_paths=source_paths,
        source_hashes=source_hashes,
        semantic_source_kind=_semantic_source_kind(rule, machine_instruction),
        runtime_class=_runtime_class(has_field_targets, has_claim_targets, has_modality_targets),
        field_target_density=field_target_density,
        claim_target_density=claim_target_density,
        modality_target_density=modality_target_density,
        total_target_density=field_target_density + claim_target_density + modality_target_density,
        has_machine_instruction=has_machine_instruction,
        has_field_targets=has_field_targets,
        has_claim_targets=has_claim_targets,
        has_modality_targets=has_modality_targets,
    )


def _build_rule_id_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, CompiledReviewRuleRow]:
    return MappingProxyType({row.rule_id: row for row in rows})


def _build_name_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, str]:
    return MappingProxyType({row.name: row.rule_id for row in rows})


def _build_severity_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.severity].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_trigger_type_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.trigger_type].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_field_target_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for target_id in row.applies_to_field_ids:
            buckets[target_id].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_claim_target_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for target_id in row.applies_to_claim_family_ids:
            buckets[target_id].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_modality_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for modality in row.applies_to_modalities:
            buckets[modality].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_runtime_class_index(rows: tuple[CompiledReviewRuleRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.runtime_class].append(row.rule_id)
    return MappingProxyType({key: tuple(sorted(ids)) for key, ids in sorted(buckets.items())})


def _build_diagnostics(rows: tuple[CompiledReviewRuleRow, ...]) -> tuple[ReviewRuleTableDiagnostic, ...]:
    diagnostics: list[ReviewRuleTableDiagnostic] = []
    for row in rows:
        if not row.has_machine_instruction:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.machine_instruction_missing",
                    message="Review rule machine instruction is empty",
                    rule_id=row.rule_id,
                )
            )
        if not row.has_field_targets:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.field_targets_missing",
                    message="Review rule has no field targets",
                    rule_id=row.rule_id,
                )
            )
        if not row.has_claim_targets:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.claim_targets_missing",
                    message="Review rule has no claim-family targets",
                    rule_id=row.rule_id,
                )
            )
        if not row.has_modality_targets:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.modality_targets_missing",
                    message="Review rule has no modality targets",
                    rule_id=row.rule_id,
                )
            )
        if row.total_target_density == 0:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.targets_missing_all",
                    message="Review rule has no field, claim, or modality targets",
                    rule_id=row.rule_id,
                )
            )
        if row.fallback_used:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="info",
                    code="review_rule_table.fallback_used",
                    message="Review rule uses fallback-derived semantics",
                    rule_id=row.rule_id,
                )
            )
        if row.severity.strip().lower() in {"", "generic", "unknown"}:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.severity_generic",
                    message="Review rule severity is generic and may need hardening",
                    rule_id=row.rule_id,
                    context={"severity": row.severity},
                )
            )
        if row.trigger_type.strip().lower() in {"", "generic", "rule", "unknown"}:
            diagnostics.append(
                ReviewRuleTableDiagnostic(
                    level="warning",
                    code="review_rule_table.trigger_type_generic",
                    message="Review rule trigger type is generic and may need hardening",
                    rule_id=row.rule_id,
                    context={"trigger_type": row.trigger_type},
                )
            )
    return tuple(diagnostics)


def _build_summary(rows: tuple[CompiledReviewRuleRow, ...]) -> ReviewRuleTableSummary:
    by_severity: dict[str, int] = defaultdict(int)
    by_trigger_type: dict[str, int] = defaultdict(int)
    by_runtime_class: dict[str, int] = defaultdict(int)
    missing_machine_instruction: list[str] = []
    without_field_targets: list[str] = []
    without_claim_targets: list[str] = []
    without_modality_targets: list[str] = []
    without_any_targets: list[str] = []
    fallback_rules: list[str] = []

    for row in rows:
        by_severity[row.severity] += 1
        by_trigger_type[row.trigger_type] += 1
        by_runtime_class[row.runtime_class] += 1
        if not row.has_machine_instruction:
            missing_machine_instruction.append(row.rule_id)
        if not row.has_field_targets:
            without_field_targets.append(row.rule_id)
        if not row.has_claim_targets:
            without_claim_targets.append(row.rule_id)
        if not row.has_modality_targets:
            without_modality_targets.append(row.rule_id)
        if row.total_target_density == 0:
            without_any_targets.append(row.rule_id)
        if row.fallback_used:
            fallback_rules.append(row.rule_id)

    return ReviewRuleTableSummary(
        total_review_rules=len(rows),
        review_rules_by_severity=MappingProxyType(dict(sorted(by_severity.items()))),
        review_rules_by_trigger_type=MappingProxyType(dict(sorted(by_trigger_type.items()))),
        review_rules_by_runtime_class=MappingProxyType(dict(sorted(by_runtime_class.items()))),
        review_rules_missing_machine_instruction=tuple(sorted(missing_machine_instruction)),
        review_rules_without_field_targets=tuple(sorted(without_field_targets)),
        review_rules_without_claim_targets=tuple(sorted(without_claim_targets)),
        review_rules_without_modality_targets=tuple(sorted(without_modality_targets)),
        review_rules_without_any_targets=tuple(sorted(without_any_targets)),
        fallback_used_rule_count=len(fallback_rules),
        rules_using_fallback_semantics=tuple(sorted(fallback_rules)),
    )


def to_jsonable_row(row: CompiledReviewRuleRow) -> dict[str, Any]:
    return {
        "rule_id": row.rule_id,
        "name": row.name,
        "severity": row.severity,
        "trigger_type": row.trigger_type,
        "machine_instruction": row.machine_instruction,
        "applies_to_field_ids": list(row.applies_to_field_ids),
        "applies_to_claim_family_ids": list(row.applies_to_claim_family_ids),
        "applies_to_modalities": list(row.applies_to_modalities),
        "fallback_used": row.fallback_used,
        "authoritative_source_role": row.authoritative_source_role,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "semantic_source_kind": row.semantic_source_kind,
        "runtime_class": row.runtime_class,
        "field_target_density": row.field_target_density,
        "claim_target_density": row.claim_target_density,
        "modality_target_density": row.modality_target_density,
        "total_target_density": row.total_target_density,
        "has_machine_instruction": row.has_machine_instruction,
        "has_field_targets": row.has_field_targets,
        "has_claim_targets": row.has_claim_targets,
        "has_modality_targets": row.has_modality_targets,
    }


def to_jsonable_summary(summary: ReviewRuleTableSummary) -> dict[str, Any]:
    return {
        "total_review_rules": summary.total_review_rules,
        "review_rules_by_severity": dict(summary.review_rules_by_severity),
        "review_rules_by_trigger_type": dict(summary.review_rules_by_trigger_type),
        "review_rules_by_runtime_class": dict(summary.review_rules_by_runtime_class),
        "review_rules_missing_machine_instruction": list(summary.review_rules_missing_machine_instruction),
        "review_rules_without_field_targets": list(summary.review_rules_without_field_targets),
        "review_rules_without_claim_targets": list(summary.review_rules_without_claim_targets),
        "review_rules_without_modality_targets": list(summary.review_rules_without_modality_targets),
        "review_rules_without_any_targets": list(summary.review_rules_without_any_targets),
        "fallback_used_rule_count": summary.fallback_used_rule_count,
        "rules_using_fallback_semantics": list(summary.rules_using_fallback_semantics),
    }


def to_jsonable_diagnostic(diag: ReviewRuleTableDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "rule_id": diag.rule_id,
        "context": dict(diag.context),
    }


def compile_review_rule_table(ir: CanonicalIR) -> CompiledReviewRuleTable:
    _validate_uniqueness(ir)
    field_ids = set(ir.fields.keys())
    claim_ids = set(ir.claim_families.keys())
    admitted_modalities = set(ir.manifest.admitted_modalities)

    rows = tuple(
        sorted(
            (
                _flatten_review_rule_spec_to_row(
                    rule=rule,
                    field_ids=field_ids,
                    claim_ids=claim_ids,
                    admitted_modalities=admitted_modalities,
                )
                for rule in ir.review_rules.values()
            ),
            key=lambda row: row.rule_id,
        )
    )
    diagnostics = _build_diagnostics(rows)
    summary = _build_summary(rows)
    return CompiledReviewRuleTable(
        rows=rows,
        by_rule_id=_build_rule_id_index(rows),
        by_name=_build_name_index(rows),
        by_severity=_build_severity_index(rows),
        by_trigger_type=_build_trigger_type_index(rows),
        by_field_target_id=_build_field_target_index(rows),
        by_claim_target_id=_build_claim_target_index(rows),
        by_modality=_build_modality_index(rows),
        by_runtime_class=_build_runtime_class_index(rows),
        diagnostics=diagnostics,
        summary=summary,
    )
