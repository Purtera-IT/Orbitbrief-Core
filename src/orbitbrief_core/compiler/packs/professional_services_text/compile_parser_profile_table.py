from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR, CanonicalParserProfile
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError
from orbitbrief_core.compiler.packs.professional_services_text.compile_allowed_masks import (
    CompiledAllowedMask,
    CompiledAllowedMasks,
)


@dataclass(frozen=True)
class CompiledParserProfileRow:
    parser_profile_id: str
    modality: str
    artifact_family: str
    role_id: str
    parser_kind: str
    structure_preservation_mode: str
    chronology_sensitive: bool
    actor_sensitive: bool
    confidence_policy: str
    allowed_field_ids: tuple[str, ...]
    allowed_claim_family_ids: tuple[str, ...]
    linked_review_rule_ids: tuple[str, ...]
    fallback_used: bool
    authoritative_source_role: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    runtime_class: str
    field_density: int
    claim_density: int
    rule_density: int


@dataclass(frozen=True)
class ParserProfileTableDiagnostic:
    level: str
    code: str
    message: str
    parser_profile_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParserProfileTableSummary:
    total_parser_profiles: int
    parser_profiles_by_modality: Mapping[str, int]
    parser_profiles_by_parser_kind: Mapping[str, int]
    parser_profiles_by_confidence_policy: Mapping[str, int]
    parser_profiles_by_runtime_class: Mapping[str, int]
    parser_profiles_using_fallback: tuple[str, ...]
    parser_profiles_with_empty_field_sets: tuple[str, ...]
    parser_profiles_with_empty_claim_sets: tuple[str, ...]
    parser_profiles_with_empty_rule_sets: tuple[str, ...]


@dataclass(frozen=True)
class CompiledParserProfileTable:
    rows: tuple[CompiledParserProfileRow, ...]
    by_parser_profile_id: Mapping[str, CompiledParserProfileRow]
    by_modality: Mapping[str, str]
    by_parser_kind: Mapping[str, tuple[str, ...]]
    by_confidence_policy: Mapping[str, tuple[str, ...]]
    by_runtime_class: Mapping[str, tuple[str, ...]]
    diagnostics: tuple[ParserProfileTableDiagnostic, ...]
    summary: ParserProfileTableSummary


def _validate_uniqueness(ir: CanonicalIR) -> None:
    profile_ids = [spec.parser_profile_id for spec in ir.parser_profiles.values()]
    modalities = [spec.modality for spec in ir.parser_profiles.values()]
    if len(set(profile_ids)) != len(profile_ids):
        raise ContractLoadError("Duplicate parser_profile_id detected in CanonicalIR.parser_profiles")
    if len(set(modalities)) != len(modalities):
        raise ContractLoadError("Duplicate modality detected in CanonicalIR.parser_profiles")


def _validate_parser_profile_spec(
    profile: CanonicalParserProfile,
    admitted_modalities: set[str],
    field_ids: set[str],
    claim_ids: set[str],
    rule_ids: set[str],
) -> None:
    if not profile.parser_profile_id:
        raise ContractLoadError("Parser profile must have non-empty parser_profile_id")
    if profile.modality not in admitted_modalities:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} has non-admitted modality: {profile.modality}"
        )
    unknown_field_ids = sorted(set(profile.allowed_field_ids) - field_ids)
    if unknown_field_ids:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} references unknown allowed_field_ids: {unknown_field_ids}"
        )
    unknown_claim_ids = sorted(set(profile.allowed_claim_family_ids) - claim_ids)
    if unknown_claim_ids:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} references unknown allowed_claim_family_ids: {unknown_claim_ids}"
        )
    unknown_rule_ids = sorted(set(profile.linked_review_rule_ids) - rule_ids)
    if unknown_rule_ids:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} references unknown linked_review_rule_ids: {unknown_rule_ids}"
        )
    if not profile.source_paths or not profile.source_hashes:
        raise ContractLoadError(f"Parser profile {profile.parser_profile_id} is missing provenance paths/hashes")
    if len(profile.source_paths) != len(profile.source_hashes):
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} has mismatched provenance tuple lengths "
            f"(paths={len(profile.source_paths)}, hashes={len(profile.source_hashes)})"
        )


def _runtime_class(profile: CanonicalParserProfile) -> str:
    mode = profile.structure_preservation_mode.strip().lower()
    is_strong_structure = mode in {"preserve", "strong", "strict", "rich"}
    if is_strong_structure and profile.chronology_sensitive and profile.actor_sensitive:
        return "rich_context_profile"
    if is_strong_structure:
        return "structure_profile"
    if profile.chronology_sensitive or profile.actor_sensitive:
        return "context_profile"
    return "basic_profile"


def _mask_for_modality(compiled_masks: CompiledAllowedMasks, modality: str) -> CompiledAllowedMask:
    mask_id = compiled_masks.by_modality.get(modality)
    if not mask_id:
        raise ContractLoadError(f"No allowed mask found for modality: {modality}")
    return compiled_masks.by_mask_id[mask_id]


def _flatten_parser_profile_to_row(
    profile: CanonicalParserProfile,
    mask: CompiledAllowedMask,
    admitted_modalities: set[str],
    field_ids: set[str],
    claim_ids: set[str],
    rule_ids: set[str],
) -> CompiledParserProfileRow:
    _validate_parser_profile_spec(profile, admitted_modalities, field_ids, claim_ids, rule_ids)

    disallowed_fields = sorted(set(profile.allowed_field_ids) - set(mask.allowed_field_ids))
    if disallowed_fields:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} allows field IDs disallowed by mask {mask.mask_id}: "
            f"{disallowed_fields}"
        )
    disallowed_claims = sorted(set(profile.allowed_claim_family_ids) - set(mask.allowed_claim_family_ids))
    if disallowed_claims:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} allows claim IDs disallowed by mask {mask.mask_id}: "
            f"{disallowed_claims}"
        )
    disallowed_rules = sorted(set(profile.linked_review_rule_ids) - set(mask.allowed_review_rule_ids))
    if disallowed_rules:
        raise ContractLoadError(
            f"Parser profile {profile.parser_profile_id} links review rules disallowed by mask {mask.mask_id}: "
            f"{disallowed_rules}"
        )

    allowed_field_ids = tuple(sorted(set(profile.allowed_field_ids) & set(mask.allowed_field_ids)))
    allowed_claim_family_ids = tuple(sorted(set(profile.allowed_claim_family_ids) & set(mask.allowed_claim_family_ids)))
    linked_review_rule_ids = tuple(sorted(set(profile.linked_review_rule_ids) & set(mask.allowed_review_rule_ids)))

    return CompiledParserProfileRow(
        parser_profile_id=profile.parser_profile_id,
        modality=profile.modality,
        artifact_family=profile.artifact_family,
        role_id=profile.role_id,
        parser_kind=" ".join(profile.parser_kind.split()),
        structure_preservation_mode=" ".join(profile.structure_preservation_mode.split()),
        chronology_sensitive=profile.chronology_sensitive,
        actor_sensitive=profile.actor_sensitive,
        confidence_policy=" ".join(profile.confidence_policy.split()),
        allowed_field_ids=allowed_field_ids,
        allowed_claim_family_ids=allowed_claim_family_ids,
        linked_review_rule_ids=linked_review_rule_ids,
        fallback_used=profile.fallback_used or mask.fallback_used,
        authoritative_source_role="enhanced_machine",
        source_paths=tuple(sorted(profile.source_paths)),
        source_hashes=tuple(sorted(profile.source_hashes)),
        runtime_class=_runtime_class(profile),
        field_density=len(allowed_field_ids),
        claim_density=len(allowed_claim_family_ids),
        rule_density=len(linked_review_rule_ids),
    )


def _build_parser_profile_id_index(rows: tuple[CompiledParserProfileRow, ...]) -> Mapping[str, CompiledParserProfileRow]:
    return MappingProxyType({row.parser_profile_id: row for row in rows})


def _build_modality_index(rows: tuple[CompiledParserProfileRow, ...]) -> Mapping[str, str]:
    return MappingProxyType({row.modality: row.parser_profile_id for row in rows})


def _build_parser_kind_index(rows: tuple[CompiledParserProfileRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.parser_kind].append(row.parser_profile_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_confidence_policy_index(rows: tuple[CompiledParserProfileRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.confidence_policy].append(row.parser_profile_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_runtime_class_index(rows: tuple[CompiledParserProfileRow, ...]) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        buckets[row.runtime_class].append(row.parser_profile_id)
    return MappingProxyType({k: tuple(sorted(v)) for k, v in sorted(buckets.items())})


def _build_diagnostics(rows: tuple[CompiledParserProfileRow, ...]) -> tuple[ParserProfileTableDiagnostic, ...]:
    diagnostics: list[ParserProfileTableDiagnostic] = []
    for row in rows:
        if row.field_density == 0:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="warning",
                    code="parser_profile_table.field_set_empty",
                    message="Parser profile has empty allowed field set.",
                    parser_profile_id=row.parser_profile_id,
                )
            )
        if row.claim_density == 0:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="warning",
                    code="parser_profile_table.claim_set_empty",
                    message="Parser profile has empty allowed claim-family set.",
                    parser_profile_id=row.parser_profile_id,
                )
            )
        if row.rule_density == 0:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="warning",
                    code="parser_profile_table.rule_set_empty",
                    message="Parser profile has empty linked review-rule set.",
                    parser_profile_id=row.parser_profile_id,
                )
            )
        if row.fallback_used:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="info",
                    code="parser_profile_table.fallback_used",
                    message="Parser profile uses fallback-derived semantics.",
                    parser_profile_id=row.parser_profile_id,
                )
            )
        if row.parser_kind.strip().lower() in {"", "generic", "unknown", "parser"}:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="warning",
                    code="parser_profile_table.parser_kind_generic",
                    message="Parser kind is generic and may need hardening.",
                    parser_profile_id=row.parser_profile_id,
                    context={"parser_kind": row.parser_kind},
                )
            )
        if row.confidence_policy.strip().lower() in {"", "generic", "unknown", "default"}:
            diagnostics.append(
                ParserProfileTableDiagnostic(
                    level="warning",
                    code="parser_profile_table.confidence_policy_generic",
                    message="Confidence policy is generic and may need hardening.",
                    parser_profile_id=row.parser_profile_id,
                    context={"confidence_policy": row.confidence_policy},
                )
            )
    return tuple(diagnostics)


def _build_summary(rows: tuple[CompiledParserProfileRow, ...]) -> ParserProfileTableSummary:
    by_modality: dict[str, int] = defaultdict(int)
    by_parser_kind: dict[str, int] = defaultdict(int)
    by_confidence_policy: dict[str, int] = defaultdict(int)
    by_runtime_class: dict[str, int] = defaultdict(int)
    using_fallback: list[str] = []
    empty_fields: list[str] = []
    empty_claims: list[str] = []
    empty_rules: list[str] = []

    for row in rows:
        by_modality[row.modality] += 1
        by_parser_kind[row.parser_kind] += 1
        by_confidence_policy[row.confidence_policy] += 1
        by_runtime_class[row.runtime_class] += 1
        if row.fallback_used:
            using_fallback.append(row.parser_profile_id)
        if row.field_density == 0:
            empty_fields.append(row.parser_profile_id)
        if row.claim_density == 0:
            empty_claims.append(row.parser_profile_id)
        if row.rule_density == 0:
            empty_rules.append(row.parser_profile_id)

    return ParserProfileTableSummary(
        total_parser_profiles=len(rows),
        parser_profiles_by_modality=MappingProxyType(dict(sorted(by_modality.items()))),
        parser_profiles_by_parser_kind=MappingProxyType(dict(sorted(by_parser_kind.items()))),
        parser_profiles_by_confidence_policy=MappingProxyType(dict(sorted(by_confidence_policy.items()))),
        parser_profiles_by_runtime_class=MappingProxyType(dict(sorted(by_runtime_class.items()))),
        parser_profiles_using_fallback=tuple(sorted(using_fallback)),
        parser_profiles_with_empty_field_sets=tuple(sorted(empty_fields)),
        parser_profiles_with_empty_claim_sets=tuple(sorted(empty_claims)),
        parser_profiles_with_empty_rule_sets=tuple(sorted(empty_rules)),
    )


def to_jsonable_row(row: CompiledParserProfileRow) -> dict[str, Any]:
    return {
        "parser_profile_id": row.parser_profile_id,
        "modality": row.modality,
        "artifact_family": row.artifact_family,
        "role_id": row.role_id,
        "parser_kind": row.parser_kind,
        "structure_preservation_mode": row.structure_preservation_mode,
        "chronology_sensitive": row.chronology_sensitive,
        "actor_sensitive": row.actor_sensitive,
        "confidence_policy": row.confidence_policy,
        "allowed_field_ids": list(row.allowed_field_ids),
        "allowed_claim_family_ids": list(row.allowed_claim_family_ids),
        "linked_review_rule_ids": list(row.linked_review_rule_ids),
        "fallback_used": row.fallback_used,
        "authoritative_source_role": row.authoritative_source_role,
        "source_paths": list(row.source_paths),
        "source_hashes": list(row.source_hashes),
        "runtime_class": row.runtime_class,
        "field_density": row.field_density,
        "claim_density": row.claim_density,
        "rule_density": row.rule_density,
    }


def to_jsonable_summary(summary: ParserProfileTableSummary) -> dict[str, Any]:
    return {
        "total_parser_profiles": summary.total_parser_profiles,
        "parser_profiles_by_modality": dict(summary.parser_profiles_by_modality),
        "parser_profiles_by_parser_kind": dict(summary.parser_profiles_by_parser_kind),
        "parser_profiles_by_confidence_policy": dict(summary.parser_profiles_by_confidence_policy),
        "parser_profiles_by_runtime_class": dict(summary.parser_profiles_by_runtime_class),
        "parser_profiles_using_fallback": list(summary.parser_profiles_using_fallback),
        "parser_profiles_with_empty_field_sets": list(summary.parser_profiles_with_empty_field_sets),
        "parser_profiles_with_empty_claim_sets": list(summary.parser_profiles_with_empty_claim_sets),
        "parser_profiles_with_empty_rule_sets": list(summary.parser_profiles_with_empty_rule_sets),
    }


def to_jsonable_diagnostic(diag: ParserProfileTableDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "parser_profile_id": diag.parser_profile_id,
        "context": dict(diag.context),
    }


def compile_parser_profile_table(
    ir: CanonicalIR,
    compiled_masks: CompiledAllowedMasks,
) -> CompiledParserProfileTable:
    _validate_uniqueness(ir)
    admitted_modalities = set(ir.manifest.admitted_modalities)
    field_ids = set(ir.fields.keys())
    claim_ids = set(ir.claim_families.keys())
    rule_ids = set(ir.review_rules.keys())

    for profile in ir.parser_profiles.values():
        _validate_parser_profile_spec(profile, admitted_modalities, field_ids, claim_ids, rule_ids)

    rows_list: list[CompiledParserProfileRow] = []
    for profile in ir.parser_profiles.values():
        rows_list.append(
            _flatten_parser_profile_to_row(
                profile=profile,
                mask=_mask_for_modality(compiled_masks, profile.modality),
                admitted_modalities=admitted_modalities,
                field_ids=field_ids,
                claim_ids=claim_ids,
                rule_ids=rule_ids,
            )
        )

    rows = tuple(
        sorted(
            rows_list,
            key=lambda row: row.parser_profile_id,
        )
    )
    diagnostics = _build_diagnostics(rows)
    summary = _build_summary(rows)

    return CompiledParserProfileTable(
        rows=rows,
        by_parser_profile_id=_build_parser_profile_id_index(rows),
        by_modality=_build_modality_index(rows),
        by_parser_kind=_build_parser_kind_index(rows),
        by_confidence_policy=_build_confidence_policy_index(rows),
        by_runtime_class=_build_runtime_class_index(rows),
        diagnostics=diagnostics,
        summary=summary,
    )
