from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalFieldSpec, CanonicalIR
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError


@dataclass(frozen=True)
class CompiledFieldRow:
    field_id: str
    field_path: str
    field_name: str
    group: str
    value_type: str
    repeatable: bool
    pre_or_post: str
    allowed_modalities: tuple[str, ...]
    human_definition: str
    machine_gloss: str
    evidence_cues: tuple[str, ...]
    anti_evidence_cues: tuple[str, ...]
    confusions: tuple[str, ...]
    linked_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    linked_projection_rule_ids: tuple[str, ...]
    fallback_used: bool
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    semantic_source_kind: str
    runtime_class: str
    linkage_density: int
    has_human_definition: bool
    has_machine_gloss: bool
    has_semantic_definition: bool
    has_rule_links: bool
    has_claim_links: bool
    has_projection_links: bool


@dataclass(frozen=True)
class FieldTableDiagnostic:
    level: str
    code: str
    message: str
    field_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldTableSummary:
    total_fields: int
    pre_fields: int
    post_fields: int
    repeatable_fields: int
    scalar_fields: int
    fields_by_group: Mapping[str, int]
    fields_by_modality: Mapping[str, int]
    fields_missing_machine_gloss: tuple[str, ...]
    fields_missing_semantic_definition: tuple[str, ...]
    fields_without_claim_links: tuple[str, ...]
    fields_without_rule_links: tuple[str, ...]
    fields_without_projection_links: tuple[str, ...]
    fallback_used_fields_count: int
    fields_using_fallback_semantics: tuple[str, ...]


@dataclass(frozen=True)
class CompiledFieldTable:
    rows: tuple[CompiledFieldRow, ...]
    by_field_id: Mapping[str, CompiledFieldRow]
    by_field_path: Mapping[str, str]
    by_group: Mapping[str, tuple[str, ...]]
    by_pre_or_post: Mapping[str, tuple[str, ...]]
    by_modality: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[FieldTableDiagnostic, ...]
    summary: FieldTableSummary


def _validate_uniqueness(ir: CanonicalIR) -> None:
    field_ids = [f.field_id for f in ir.fields.values()]
    field_paths = [f.field_path for f in ir.fields.values()]
    if len(set(field_ids)) != len(field_ids):
        raise ContractLoadError("Duplicate field_id detected in CanonicalIR.fields")
    if len(set(field_paths)) != len(field_paths):
        raise ContractLoadError("Duplicate field_path detected in CanonicalIR.fields")


def _validate_field_spec(field: CanonicalFieldSpec, admitted_modalities: set[str]) -> None:
    if not field.field_id or not field.field_path:
        raise ContractLoadError("Field must have non-empty field_id and field_path")
    if not field.field_name or not field.group:
        raise ContractLoadError(f"Field {field.field_id} must have non-empty field_name and group")
    if field.pre_or_post not in {"pre", "post"}:
        raise ContractLoadError(f"Field {field.field_id} has invalid pre_or_post value: {field.pre_or_post}")
    if not field.allowed_modalities:
        raise ContractLoadError(f"Field {field.field_id} has empty allowed_modalities")
    invalid_modalities = sorted(set(field.allowed_modalities) - admitted_modalities)
    if invalid_modalities:
        raise ContractLoadError(
            f"Field {field.field_id} references non-admitted modalities: {invalid_modalities}"
        )
    if not field.source_paths or not field.source_hashes:
        raise ContractLoadError(f"Field {field.field_id} is missing provenance paths/hashes")
    if len(field.source_paths) != len(field.source_hashes):
        raise ContractLoadError(
            f"Field {field.field_id} has mismatched provenance tuple lengths "
            f"(paths={len(field.source_paths)}, hashes={len(field.source_hashes)})"
        )


def _semantic_source_kind(field: CanonicalFieldSpec, human_definition: str, machine_gloss: str) -> str:
    if field.fallback_used:
        return "fallback"
    if human_definition or machine_gloss:
        return "primary"
    return "legal_only"


def _runtime_class(field: CanonicalFieldSpec) -> str:
    cardinality = "list" if field.repeatable else "scalar"
    return f"{cardinality}_{field.pre_or_post}"


def _flatten_field_spec_to_row(field: CanonicalFieldSpec, admitted_modalities: set[str]) -> CompiledFieldRow:
    _validate_field_spec(field, admitted_modalities)
    allowed_modalities = tuple(sorted(field.allowed_modalities))
    claim_links = tuple(sorted(field.linked_claim_family_ids))
    rule_links = tuple(sorted(field.linked_review_rule_ids))
    projection_links = tuple(sorted(field.linked_projection_rule_ids))
    source_paths = tuple(sorted(field.source_paths))
    source_hashes = tuple(sorted(field.source_hashes))
    machine_gloss = " ".join(field.machine_gloss.split())
    human_definition = " ".join(field.human_definition.split())
    has_human_definition = bool(human_definition)
    has_machine_gloss = bool(machine_gloss)
    has_semantic_definition = has_human_definition
    has_rule_links = bool(rule_links)
    has_claim_links = bool(claim_links)
    has_projection_links = bool(projection_links)

    return CompiledFieldRow(
        field_id=field.field_id,
        field_path=field.field_path,
        field_name=field.field_name,
        group=field.group,
        value_type=field.value_type,
        repeatable=field.repeatable,
        pre_or_post=field.pre_or_post,
        allowed_modalities=allowed_modalities,
        human_definition=human_definition,
        machine_gloss=machine_gloss,
        evidence_cues=tuple(sorted(field.evidence_cues)),
        anti_evidence_cues=tuple(sorted(field.anti_evidence_cues)),
        confusions=tuple(sorted(field.confusions)),
        linked_claim_family_ids=claim_links,
        linked_review_rule_ids=rule_links,
        linked_projection_rule_ids=projection_links,
        fallback_used=field.fallback_used,
        authoritative_source_role=field.authoritative_source_role,
        source_paths=source_paths,
        source_hashes=source_hashes,
        semantic_source_kind=_semantic_source_kind(field, human_definition, machine_gloss),
        runtime_class=_runtime_class(field),
        linkage_density=len(claim_links) + len(rule_links) + len(projection_links),
        has_human_definition=has_human_definition,
        has_machine_gloss=has_machine_gloss,
        has_semantic_definition=has_semantic_definition,
        has_rule_links=has_rule_links,
        has_claim_links=has_claim_links,
        has_projection_links=has_projection_links,
    )


def _build_field_id_index(rows: tuple[CompiledFieldRow, ...]) -> Mapping[str, CompiledFieldRow]:
    return MappingProxyType({row.field_id: row for row in rows})


def _build_field_path_index(rows: tuple[CompiledFieldRow, ...]) -> Mapping[str, str]:
    return MappingProxyType({row.field_path: row.field_id for row in rows})


def _build_group_index(rows: tuple[CompiledFieldRow, ...]) -> Mapping[str, tuple[str, ...]]:
    by_group: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_group[row.group].append(row.field_id)
    return MappingProxyType({group: tuple(sorted(ids)) for group, ids in sorted(by_group.items())})


def _build_pre_or_post_index(rows: tuple[CompiledFieldRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.pre_or_post].append(row.field_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_modality_index(rows: tuple[CompiledFieldRow, ...]) -> Mapping[str, tuple[str, ...]]:
    by_modality: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for modality in row.allowed_modalities:
            by_modality[modality].append(row.field_id)
    return MappingProxyType({modality: tuple(sorted(ids)) for modality, ids in sorted(by_modality.items())})


def _build_diagnostics(rows: tuple[CompiledFieldRow, ...]) -> tuple[FieldTableDiagnostic, ...]:
    diagnostics: list[FieldTableDiagnostic] = []
    for row in rows:
        if not row.machine_gloss:
            diagnostics.append(
                FieldTableDiagnostic("warning", "field_table.machine_gloss_missing", "Machine gloss is empty", row.field_id)
            )
        if not row.human_definition:
            diagnostics.append(
                FieldTableDiagnostic(
                    "warning",
                    "field_table.semantic_definition_missing",
                    "Human semantic definition is empty",
                    row.field_id,
                )
            )
        if not row.has_claim_links:
            diagnostics.append(
                FieldTableDiagnostic("warning", "field_table.claim_links_missing", "No claim links on field", row.field_id)
            )
        if not row.has_rule_links:
            diagnostics.append(
                FieldTableDiagnostic("warning", "field_table.rule_links_missing", "No review rule links on field", row.field_id)
            )
        if not row.has_projection_links:
            diagnostics.append(
                FieldTableDiagnostic(
                    "warning",
                    "field_table.projection_links_missing",
                    "No projection rule links on field",
                    row.field_id,
                )
            )
        if row.fallback_used:
            diagnostics.append(
                FieldTableDiagnostic("info", "field_table.fallback_used", "Field uses fallback-derived semantics", row.field_id)
            )
        if not row.value_type or row.value_type.lower() == "unknown":
            diagnostics.append(
                FieldTableDiagnostic(
                    "warning",
                    "field_table.value_type_unknown",
                    "Field value_type is unknown and should be tightened.",
                    row.field_id,
                )
            )
        if not row.machine_gloss and not row.human_definition:
            diagnostics.append(
                FieldTableDiagnostic(
                    "warning",
                    "field_table.semantic_text_missing",
                    "Field has neither machine gloss nor human definition.",
                    row.field_id,
                )
            )
    return tuple(diagnostics)


def _build_summary(rows: tuple[CompiledFieldRow, ...]) -> FieldTableSummary:
    fields_by_group: dict[str, int] = defaultdict(int)
    fields_by_modality: dict[str, int] = defaultdict(int)
    missing_machine_gloss: list[str] = []
    missing_semantic_definition: list[str] = []
    without_claim_links: list[str] = []
    without_rule_links: list[str] = []
    without_projection_links: list[str] = []
    fallback_fields: list[str] = []

    pre_fields = 0
    post_fields = 0
    repeatable_fields = 0
    scalar_fields = 0

    for row in rows:
        fields_by_group[row.group] += 1
        for modality in row.allowed_modalities:
            fields_by_modality[modality] += 1
        if row.pre_or_post == "pre":
            pre_fields += 1
        else:
            post_fields += 1
        if row.repeatable:
            repeatable_fields += 1
        else:
            scalar_fields += 1
        if not row.machine_gloss:
            missing_machine_gloss.append(row.field_id)
        if not row.has_semantic_definition:
            missing_semantic_definition.append(row.field_id)
        if not row.has_claim_links:
            without_claim_links.append(row.field_id)
        if not row.has_rule_links:
            without_rule_links.append(row.field_id)
        if not row.has_projection_links:
            without_projection_links.append(row.field_id)
        if row.fallback_used:
            fallback_fields.append(row.field_id)

    return FieldTableSummary(
        total_fields=len(rows),
        pre_fields=pre_fields,
        post_fields=post_fields,
        repeatable_fields=repeatable_fields,
        scalar_fields=scalar_fields,
        fields_by_group=MappingProxyType(dict(sorted(fields_by_group.items()))),
        fields_by_modality=MappingProxyType(dict(sorted(fields_by_modality.items()))),
        fields_missing_machine_gloss=tuple(sorted(missing_machine_gloss)),
        fields_missing_semantic_definition=tuple(sorted(missing_semantic_definition)),
        fields_without_claim_links=tuple(sorted(without_claim_links)),
        fields_without_rule_links=tuple(sorted(without_rule_links)),
        fields_without_projection_links=tuple(sorted(without_projection_links)),
        fallback_used_fields_count=len(fallback_fields),
        fields_using_fallback_semantics=tuple(sorted(fallback_fields)),
    )


def to_jsonable_row(row: CompiledFieldRow) -> dict[str, Any]:
    return {
        "field_id": row.field_id,
        "field_path": row.field_path,
        "field_name": row.field_name,
        "group": row.group,
        "value_type": row.value_type,
        "repeatable": row.repeatable,
        "pre_or_post": row.pre_or_post,
        "allowed_modalities": list(row.allowed_modalities),
        "human_definition": row.human_definition,
        "machine_gloss": row.machine_gloss,
        "evidence_cues": list(row.evidence_cues),
        "anti_evidence_cues": list(row.anti_evidence_cues),
        "confusions": list(row.confusions),
        "linked_claim_family_ids": list(row.linked_claim_family_ids),
        "linked_review_rule_ids": list(row.linked_review_rule_ids),
        "linked_projection_rule_ids": list(row.linked_projection_rule_ids),
        "fallback_used": row.fallback_used,
        "authoritative_source_role": row.authoritative_source_role,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "semantic_source_kind": row.semantic_source_kind,
        "runtime_class": row.runtime_class,
        "linkage_density": row.linkage_density,
        "has_human_definition": row.has_human_definition,
        "has_machine_gloss": row.has_machine_gloss,
        "has_semantic_definition": row.has_semantic_definition,
        "has_rule_links": row.has_rule_links,
        "has_claim_links": row.has_claim_links,
        "has_projection_links": row.has_projection_links,
    }


def to_jsonable_summary(summary: FieldTableSummary) -> dict[str, Any]:
    return {
        "total_fields": summary.total_fields,
        "pre_fields": summary.pre_fields,
        "post_fields": summary.post_fields,
        "repeatable_fields": summary.repeatable_fields,
        "scalar_fields": summary.scalar_fields,
        "fields_by_group": dict(summary.fields_by_group),
        "fields_by_modality": dict(summary.fields_by_modality),
        "fields_missing_machine_gloss": list(summary.fields_missing_machine_gloss),
        "fields_missing_semantic_definition": list(summary.fields_missing_semantic_definition),
        "fields_without_claim_links": list(summary.fields_without_claim_links),
        "fields_without_rule_links": list(summary.fields_without_rule_links),
        "fields_without_projection_links": list(summary.fields_without_projection_links),
        "fallback_used_fields_count": summary.fallback_used_fields_count,
        "fields_using_fallback_semantics": list(summary.fields_using_fallback_semantics),
    }


def to_jsonable_diagnostic(diag: FieldTableDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "field_id": diag.field_id,
        "context": dict(diag.context),
    }


def compile_field_table(ir: CanonicalIR) -> CompiledFieldTable:
    _validate_uniqueness(ir)
    admitted_modalities = set(ir.manifest.admitted_modalities)

    rows = tuple(
        sorted(
            (
                _flatten_field_spec_to_row(field, admitted_modalities)
                for field in ir.fields.values()
            ),
            key=lambda row: row.field_id,
        )
    )
    diagnostics = _build_diagnostics(rows)
    summary = _build_summary(rows)
    return CompiledFieldTable(
        rows=rows,
        by_field_id=_build_field_id_index(rows),
        by_field_path=_build_field_path_index(rows),
        by_group=_build_group_index(rows),
        by_pre_or_post=_build_pre_or_post_index(rows),
        by_modality=_build_modality_index(rows),
        diagnostics=diagnostics,
        summary=summary,
    )
