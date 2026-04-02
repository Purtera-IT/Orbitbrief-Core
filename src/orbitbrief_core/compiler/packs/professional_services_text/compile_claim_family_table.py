from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalClaimFamilySpec, CanonicalIR
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError


@dataclass(frozen=True)
class CompiledClaimFamilyRow:
    claim_family_id: str
    name: str
    group: str
    human_definition: str
    machine_gloss: str
    evidence_patterns: tuple[str, ...]
    negative_patterns: tuple[str, ...]
    confusions: tuple[str, ...]
    projection_target_field_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    linked_example_ids: tuple[str, ...]
    linked_negative_example_ids: tuple[str, ...]
    fallback_used: bool
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    semantic_source_kind: str
    runtime_class: str
    projection_density: int
    review_link_density: int
    confusion_degree: int
    has_human_definition: bool
    has_machine_gloss: bool
    has_semantic_definition: bool
    has_projection_targets: bool
    has_review_rule_links: bool
    has_evidence_patterns: bool
    has_negative_patterns: bool


@dataclass(frozen=True)
class ClaimFamilyTableDiagnostic:
    level: str
    code: str
    message: str
    claim_family_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimFamilyTableSummary:
    total_claim_families: int
    claim_families_by_group: Mapping[str, int]
    claim_families_by_runtime_class: Mapping[str, int]
    claim_families_missing_machine_gloss: tuple[str, ...]
    claim_families_missing_semantic_definition: tuple[str, ...]
    claim_families_without_projection_targets: tuple[str, ...]
    claim_families_without_review_rule_links: tuple[str, ...]
    claim_families_without_evidence_patterns: tuple[str, ...]
    claim_families_without_negative_patterns: tuple[str, ...]
    fallback_used_claim_family_count: int
    claim_families_using_fallback_semantics: tuple[str, ...]


@dataclass(frozen=True)
class CompiledClaimFamilyTable:
    rows: tuple[CompiledClaimFamilyRow, ...]
    by_claim_family_id: Mapping[str, CompiledClaimFamilyRow]
    by_name: Mapping[str, str]
    by_group: Mapping[str, tuple[str, ...]]
    by_projection_target_field_id: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[ClaimFamilyTableDiagnostic, ...]
    summary: ClaimFamilyTableSummary


def _validate_uniqueness(ir: CanonicalIR) -> None:
    ids = [spec.claim_family_id for spec in ir.claim_families.values()]
    names = [spec.name for spec in ir.claim_families.values()]
    if len(set(ids)) != len(ids):
        raise ContractLoadError("Duplicate claim_family_id detected in CanonicalIR.claim_families")
    if len(set(names)) != len(names):
        raise ContractLoadError("Duplicate claim family name detected in CanonicalIR.claim_families")


def _validate_claim_family_spec(
    claim_family: CanonicalClaimFamilySpec,
    field_ids: set[str],
    rule_ids: set[str],
) -> None:
    if not claim_family.claim_family_id:
        raise ContractLoadError("Claim family must have non-empty claim_family_id")
    if not claim_family.name:
        raise ContractLoadError(f"Claim family {claim_family.claim_family_id} must have non-empty name")
    if not claim_family.group:
        raise ContractLoadError(f"Claim family {claim_family.claim_family_id} must have non-empty group")
    if not claim_family.source_paths or not claim_family.source_hashes:
        raise ContractLoadError(f"Claim family {claim_family.claim_family_id} is missing provenance paths/hashes")
    if len(claim_family.source_paths) != len(claim_family.source_hashes):
        raise ContractLoadError(
            f"Claim family {claim_family.claim_family_id} has mismatched provenance tuple lengths "
            f"(paths={len(claim_family.source_paths)}, hashes={len(claim_family.source_hashes)})"
        )
    unknown_target_ids = sorted(set(claim_family.projection_target_field_ids) - field_ids)
    if unknown_target_ids:
        raise ContractLoadError(
            f"Claim family {claim_family.claim_family_id} references unknown projection target field IDs: "
            f"{unknown_target_ids}"
        )
    unknown_rule_ids = sorted(set(claim_family.linked_review_rule_ids) - rule_ids)
    if unknown_rule_ids:
        raise ContractLoadError(
            f"Claim family {claim_family.claim_family_id} references unknown linked review rule IDs: "
            f"{unknown_rule_ids}"
        )


def _semantic_source_kind(claim_family: CanonicalClaimFamilySpec, human_definition: str, machine_gloss: str) -> str:
    if claim_family.fallback_used:
        return "fallback"
    if human_definition and machine_gloss:
        return "primary"
    if human_definition or machine_gloss:
        return "minimal"
    return "unknown"


def _runtime_class(has_projection_targets: bool, has_review_rule_links: bool) -> str:
    if has_projection_targets and has_review_rule_links:
        return "projecting_reviewed"
    if has_projection_targets:
        return "projecting"
    if has_review_rule_links:
        return "review_only"
    return "semantic_only"


def _flatten_claim_family_spec_to_row(
    claim_family: CanonicalClaimFamilySpec,
    field_ids: set[str],
    rule_ids: set[str],
) -> CompiledClaimFamilyRow:
    _validate_claim_family_spec(claim_family, field_ids, rule_ids)

    human_definition = " ".join(claim_family.human_definition.split())
    machine_gloss = " ".join(claim_family.machine_gloss.split())

    projection_target_field_ids = tuple(sorted(claim_family.projection_target_field_ids))
    linked_review_rule_ids = tuple(sorted(claim_family.linked_review_rule_ids))
    linked_example_ids = tuple(sorted(claim_family.linked_example_ids))
    linked_negative_example_ids = tuple(sorted(claim_family.linked_negative_example_ids))

    has_human_definition = bool(human_definition)
    has_machine_gloss = bool(machine_gloss)
    has_projection_targets = bool(projection_target_field_ids)
    has_review_rule_links = bool(linked_review_rule_ids)
    has_evidence_patterns = bool(claim_family.evidence_patterns)
    has_negative_patterns = bool(claim_family.negative_patterns)

    return CompiledClaimFamilyRow(
        claim_family_id=claim_family.claim_family_id,
        name=claim_family.name,
        group=claim_family.group,
        human_definition=human_definition,
        machine_gloss=machine_gloss,
        evidence_patterns=tuple(sorted(claim_family.evidence_patterns)),
        negative_patterns=tuple(sorted(claim_family.negative_patterns)),
        confusions=tuple(sorted(claim_family.confusions)),
        projection_target_field_ids=projection_target_field_ids,
        linked_review_rule_ids=linked_review_rule_ids,
        linked_example_ids=linked_example_ids,
        linked_negative_example_ids=linked_negative_example_ids,
        fallback_used=claim_family.fallback_used,
        authoritative_source_role=claim_family.authoritative_source_role,
        source_paths=tuple(sorted(claim_family.source_paths)),
        source_hashes=tuple(sorted(claim_family.source_hashes)),
        semantic_source_kind=_semantic_source_kind(claim_family, human_definition, machine_gloss),
        runtime_class=_runtime_class(has_projection_targets, has_review_rule_links),
        projection_density=len(projection_target_field_ids),
        review_link_density=len(linked_review_rule_ids),
        confusion_degree=len(claim_family.confusions),
        has_human_definition=has_human_definition,
        has_machine_gloss=has_machine_gloss,
        has_semantic_definition=has_human_definition,
        has_projection_targets=has_projection_targets,
        has_review_rule_links=has_review_rule_links,
        has_evidence_patterns=has_evidence_patterns,
        has_negative_patterns=has_negative_patterns,
    )


def _build_claim_family_id_index(rows: tuple[CompiledClaimFamilyRow, ...]) -> Mapping[str, CompiledClaimFamilyRow]:
    return MappingProxyType({row.claim_family_id: row for row in rows})


def _build_name_index(rows: tuple[CompiledClaimFamilyRow, ...]) -> Mapping[str, str]:
    return MappingProxyType({row.name: row.claim_family_id for row in rows})


def _build_group_index(rows: tuple[CompiledClaimFamilyRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.group].append(row.claim_family_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_projection_target_index(rows: tuple[CompiledClaimFamilyRow, ...]) -> Mapping[str, tuple[str, ...]]:
    target_to_claim_ids: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for target_id in row.projection_target_field_ids:
            target_to_claim_ids[target_id].append(row.claim_family_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(target_to_claim_ids.items())})


def _build_runtime_class_index(rows: tuple[CompiledClaimFamilyRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.runtime_class].append(row.claim_family_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_diagnostics(rows: tuple[CompiledClaimFamilyRow, ...]) -> tuple[ClaimFamilyTableDiagnostic, ...]:
    diagnostics: list[ClaimFamilyTableDiagnostic] = []
    for row in rows:
        if not row.machine_gloss:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.machine_gloss_missing",
                    "Machine gloss is empty",
                    row.claim_family_id,
                )
            )
        if not row.human_definition:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.semantic_definition_missing",
                    "Human semantic definition is empty",
                    row.claim_family_id,
                )
            )
        if not row.has_projection_targets:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.projection_targets_missing",
                    "No projection targets on claim family",
                    row.claim_family_id,
                )
            )
        if not row.has_review_rule_links:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.review_rule_links_missing",
                    "No linked review rules on claim family",
                    row.claim_family_id,
                )
            )
        if not row.has_evidence_patterns:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.evidence_patterns_missing",
                    "No evidence patterns on claim family",
                    row.claim_family_id,
                )
            )
        if not row.has_negative_patterns:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.negative_patterns_missing",
                    "No negative patterns on claim family",
                    row.claim_family_id,
                )
            )
        if row.fallback_used:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "info",
                    "claim_family_table.fallback_used",
                    "Claim family uses fallback-derived semantics",
                    row.claim_family_id,
                )
            )
        if row.group in {"default", "misc", "general"}:
            diagnostics.append(
                ClaimFamilyTableDiagnostic(
                    "warning",
                    "claim_family_table.group_too_generic",
                    "Claim family group is generic and may need hardening.",
                    row.claim_family_id,
                    context={"group": row.group},
                )
            )
    return tuple(diagnostics)


def _build_summary(rows: tuple[CompiledClaimFamilyRow, ...]) -> ClaimFamilyTableSummary:
    by_group: dict[str, int] = defaultdict(int)
    by_runtime_class: dict[str, int] = defaultdict(int)
    missing_machine_gloss: list[str] = []
    missing_semantic_definition: list[str] = []
    without_projection_targets: list[str] = []
    without_review_rule_links: list[str] = []
    without_evidence_patterns: list[str] = []
    without_negative_patterns: list[str] = []
    using_fallback: list[str] = []

    for row in rows:
        by_group[row.group] += 1
        by_runtime_class[row.runtime_class] += 1
        if not row.has_machine_gloss:
            missing_machine_gloss.append(row.claim_family_id)
        if not row.has_semantic_definition:
            missing_semantic_definition.append(row.claim_family_id)
        if not row.has_projection_targets:
            without_projection_targets.append(row.claim_family_id)
        if not row.has_review_rule_links:
            without_review_rule_links.append(row.claim_family_id)
        if not row.has_evidence_patterns:
            without_evidence_patterns.append(row.claim_family_id)
        if not row.has_negative_patterns:
            without_negative_patterns.append(row.claim_family_id)
        if row.fallback_used:
            using_fallback.append(row.claim_family_id)

    return ClaimFamilyTableSummary(
        total_claim_families=len(rows),
        claim_families_by_group=MappingProxyType(dict(sorted(by_group.items()))),
        claim_families_by_runtime_class=MappingProxyType(dict(sorted(by_runtime_class.items()))),
        claim_families_missing_machine_gloss=tuple(sorted(missing_machine_gloss)),
        claim_families_missing_semantic_definition=tuple(sorted(missing_semantic_definition)),
        claim_families_without_projection_targets=tuple(sorted(without_projection_targets)),
        claim_families_without_review_rule_links=tuple(sorted(without_review_rule_links)),
        claim_families_without_evidence_patterns=tuple(sorted(without_evidence_patterns)),
        claim_families_without_negative_patterns=tuple(sorted(without_negative_patterns)),
        fallback_used_claim_family_count=len(using_fallback),
        claim_families_using_fallback_semantics=tuple(sorted(using_fallback)),
    )


def to_jsonable_row(row: CompiledClaimFamilyRow) -> dict[str, Any]:
    return {
        "claim_family_id": row.claim_family_id,
        "name": row.name,
        "group": row.group,
        "human_definition": row.human_definition,
        "machine_gloss": row.machine_gloss,
        "evidence_patterns": list(row.evidence_patterns),
        "negative_patterns": list(row.negative_patterns),
        "confusions": list(row.confusions),
        "projection_target_field_ids": list(row.projection_target_field_ids),
        "linked_review_rule_ids": list(row.linked_review_rule_ids),
        "linked_example_ids": list(row.linked_example_ids),
        "linked_negative_example_ids": list(row.linked_negative_example_ids),
        "fallback_used": row.fallback_used,
        "authoritative_source_role": row.authoritative_source_role,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "semantic_source_kind": row.semantic_source_kind,
        "runtime_class": row.runtime_class,
        "projection_density": row.projection_density,
        "review_link_density": row.review_link_density,
        "confusion_degree": row.confusion_degree,
        "has_human_definition": row.has_human_definition,
        "has_machine_gloss": row.has_machine_gloss,
        "has_semantic_definition": row.has_semantic_definition,
        "has_projection_targets": row.has_projection_targets,
        "has_review_rule_links": row.has_review_rule_links,
        "has_evidence_patterns": row.has_evidence_patterns,
        "has_negative_patterns": row.has_negative_patterns,
    }


def to_jsonable_summary(summary: ClaimFamilyTableSummary) -> dict[str, Any]:
    return {
        "total_claim_families": summary.total_claim_families,
        "claim_families_by_group": dict(summary.claim_families_by_group),
        "claim_families_by_runtime_class": dict(summary.claim_families_by_runtime_class),
        "claim_families_missing_machine_gloss": list(summary.claim_families_missing_machine_gloss),
        "claim_families_missing_semantic_definition": list(summary.claim_families_missing_semantic_definition),
        "claim_families_without_projection_targets": list(summary.claim_families_without_projection_targets),
        "claim_families_without_review_rule_links": list(summary.claim_families_without_review_rule_links),
        "claim_families_without_evidence_patterns": list(summary.claim_families_without_evidence_patterns),
        "claim_families_without_negative_patterns": list(summary.claim_families_without_negative_patterns),
        "fallback_used_claim_family_count": summary.fallback_used_claim_family_count,
        "claim_families_using_fallback_semantics": list(summary.claim_families_using_fallback_semantics),
    }


def to_jsonable_diagnostic(diag: ClaimFamilyTableDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "claim_family_id": diag.claim_family_id,
        "context": dict(diag.context),
    }


def compile_claim_family_table(ir: CanonicalIR) -> CompiledClaimFamilyTable:
    _validate_uniqueness(ir)
    field_ids = set(ir.fields.keys())
    rule_ids = set(ir.review_rules.keys())

    rows = tuple(
        sorted(
            (
                _flatten_claim_family_spec_to_row(
                    claim_family=claim_family,
                    field_ids=field_ids,
                    rule_ids=rule_ids,
                )
                for claim_family in ir.claim_families.values()
            ),
            key=lambda row: row.claim_family_id,
        )
    )
    diagnostics = _build_diagnostics(rows)
    summary = _build_summary(rows)
    return CompiledClaimFamilyTable(
        rows=rows,
        by_claim_family_id=_build_claim_family_id_index(rows),
        by_name=_build_name_index(rows),
        by_group=_build_group_index(rows),
        by_projection_target_field_id=_build_projection_target_index(rows),
        by_runtime_class=_build_runtime_class_index(rows),
        diagnostics=diagnostics,
        summary=summary,
    )
