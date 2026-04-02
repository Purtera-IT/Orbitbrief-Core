from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from orbitbrief_core.compiler.core.canonical_ir import CanonicalIR
from orbitbrief_core.compiler.core.load_contracts import ContractLoadError
from orbitbrief_core.compiler.packs.professional_services_text.compile_claim_family_table import (
    CompiledClaimFamilyTable,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_field_table import (
    CompiledFieldTable,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_projection_rule_table import (
    CompiledProjectionRuleTable,
)
from orbitbrief_core.compiler.packs.professional_services_text.compile_review_rule_table import (
    CompiledReviewRuleTable,
)


@dataclass(frozen=True)
class CompiledAllowedMask:
    mask_id: str
    pack_id: str
    artifact_family: str
    role_id: str
    modality: str
    allowed_field_ids: tuple[str, ...]
    allowed_claim_family_ids: tuple[str, ...]
    allowed_review_rule_ids: tuple[str, ...]
    allowed_projection_rule_ids: tuple[str, ...]
    denied_field_ids: tuple[str, ...]
    denied_claim_family_ids: tuple[str, ...]
    denied_review_rule_ids: tuple[str, ...]
    denied_projection_rule_ids: tuple[str, ...]
    mask_source_kind: str
    fallback_used: bool
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    slice_fingerprint: str


@dataclass(frozen=True)
class AllowedMaskDiagnostic:
    level: str
    code: str
    message: str
    mask_id: str | None = None
    context: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AllowedMaskSummary:
    total_masks: int
    masks_by_modality: Mapping[str, int]
    allowed_field_counts_by_modality: Mapping[str, int]
    allowed_claim_family_counts_by_modality: Mapping[str, int]
    allowed_review_rule_counts_by_modality: Mapping[str, int]
    allowed_projection_rule_counts_by_modality: Mapping[str, int]
    empty_masks: tuple[str, ...]
    masks_using_fallback: tuple[str, ...]


@dataclass(frozen=True)
class CompiledAllowedMasks:
    masks: tuple[CompiledAllowedMask, ...]
    by_mask_id: Mapping[str, CompiledAllowedMask]
    by_modality: Mapping[str, str]
    diagnostics: tuple[AllowedMaskDiagnostic, ...]
    summary: AllowedMaskSummary


def _make_mask_id(pack_id: str, modality: str) -> str:
    return f"mask:{pack_id}:{modality}"


def _validate_inputs(
    ir: CanonicalIR,
    field_table: CompiledFieldTable,
    claim_table: CompiledClaimFamilyTable,
    review_rule_table: CompiledReviewRuleTable,
    projection_rule_table: CompiledProjectionRuleTable,
) -> None:
    admitted = set(ir.manifest.admitted_modalities)
    if not admitted:
        raise ContractLoadError("Cannot compile allowed masks with no admitted modalities")
    if set(field_table.by_field_id.keys()) - set(ir.fields.keys()):
        raise ContractLoadError("Field table includes field IDs not present in CanonicalIR.fields")
    if set(claim_table.by_claim_family_id.keys()) - set(ir.claim_families.keys()):
        raise ContractLoadError("Claim table includes claim IDs not present in CanonicalIR.claim_families")
    if set(review_rule_table.by_rule_id.keys()) - set(ir.review_rules.keys()):
        raise ContractLoadError("Review rule table includes rule IDs not present in CanonicalIR.review_rules")
    if set(projection_rule_table.by_projection_rule_id.keys()) - set(ir.projection_rules.keys()):
        raise ContractLoadError("Projection rule table includes projection IDs not present in CanonicalIR.projection_rules")


def _allowed_fields_for_modality(
    field_table: CompiledFieldTable,
    modality: str,
) -> tuple[str, ...]:
    return tuple(sorted(field_table.by_modality.get(modality, ())))


def _allowed_claim_families_for_modality(
    claim_table: CompiledClaimFamilyTable,
    allowed_field_ids: tuple[str, ...],
) -> tuple[str, ...]:
    allowed_field_set = set(allowed_field_ids)
    out: list[str] = []
    for row in claim_table.rows:
        if any(field_id in allowed_field_set for field_id in row.projection_target_field_ids):
            out.append(row.claim_family_id)
    return tuple(sorted(out))


def _allowed_review_rules_for_modality(
    review_rule_table: CompiledReviewRuleTable,
    allowed_field_ids: tuple[str, ...],
    allowed_claim_family_ids: tuple[str, ...],
    modality: str,
) -> tuple[str, ...]:
    allowed_field_set = set(allowed_field_ids)
    allowed_claim_set = set(allowed_claim_family_ids)
    out: list[str] = []
    for row in review_rule_table.rows:
        has_allowed_field = any(field_id in allowed_field_set for field_id in row.applies_to_field_ids)
        has_allowed_claim = any(claim_id in allowed_claim_set for claim_id in row.applies_to_claim_family_ids)
        targets_modality = modality in row.applies_to_modalities
        is_global = _is_global_rule(row)
        if has_allowed_field or has_allowed_claim or targets_modality or is_global:
            out.append(row.rule_id)
    return tuple(sorted(out))


def _allowed_projection_rules_for_modality(
    projection_rule_table: CompiledProjectionRuleTable,
    allowed_field_ids: tuple[str, ...],
    allowed_claim_family_ids: tuple[str, ...],
) -> tuple[str, ...]:
    allowed_field_set = set(allowed_field_ids)
    allowed_claim_set = set(allowed_claim_family_ids)
    out: list[str] = []
    for row in projection_rule_table.rows:
        if row.source_claim_family_id not in allowed_claim_set:
            continue
        if not all(field_id in allowed_field_set for field_id in row.target_field_ids):
            continue
        out.append(row.projection_rule_id)
    return tuple(sorted(out))


def _denied_ids(all_ids: tuple[str, ...], allowed_ids: tuple[str, ...]) -> tuple[str, ...]:
    allowed_set = set(allowed_ids)
    return tuple(sorted(item for item in all_ids if item not in allowed_set))


def _slice_fingerprint(*parts: tuple[str, ...]) -> str:
    payload = "|".join(
        [",".join(tuple(sorted(part))) for part in parts]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_global_rule(row: Any) -> bool:
    return bool(
        getattr(row, "total_target_density", 0) == 0
        and not getattr(row, "applies_to_modalities", ())
    )


def _build_mask(
    ir: CanonicalIR,
    field_table: CompiledFieldTable,
    claim_table: CompiledClaimFamilyTable,
    review_rule_table: CompiledReviewRuleTable,
    projection_rule_table: CompiledProjectionRuleTable,
    modality: str,
) -> CompiledAllowedMask:
    all_field_ids = tuple(sorted(field_table.by_field_id.keys()))
    all_claim_ids = tuple(sorted(claim_table.by_claim_family_id.keys()))
    all_rule_ids = tuple(sorted(review_rule_table.by_rule_id.keys()))
    all_projection_ids = tuple(sorted(projection_rule_table.by_projection_rule_id.keys()))

    allowed_field_ids = _allowed_fields_for_modality(field_table, modality)
    allowed_claim_family_ids = _allowed_claim_families_for_modality(claim_table, allowed_field_ids)
    allowed_review_rule_ids = _allowed_review_rules_for_modality(
        review_rule_table,
        allowed_field_ids,
        allowed_claim_family_ids,
        modality,
    )
    allowed_projection_rule_ids = _allowed_projection_rules_for_modality(
        projection_rule_table,
        allowed_field_ids,
        allowed_claim_family_ids,
    )

    denied_field_ids = _denied_ids(all_field_ids, allowed_field_ids)
    denied_claim_family_ids = _denied_ids(all_claim_ids, allowed_claim_family_ids)
    denied_review_rule_ids = _denied_ids(all_rule_ids, allowed_review_rule_ids)
    denied_projection_rule_ids = _denied_ids(all_projection_ids, allowed_projection_rule_ids)

    source_paths = tuple(sorted({*ir.manifest.source_paths.values()}))
    source_hashes = tuple(sorted({*ir.manifest.source_hashes.values()}))
    fallback_used = bool(ir.manifest.fallback_used_for)

    if fallback_used:
        mask_source_kind = "fallback"
    elif allowed_field_ids or allowed_claim_family_ids or allowed_review_rule_ids or allowed_projection_rule_ids:
        mask_source_kind = "primary"
    else:
        mask_source_kind = "unknown"

    mask = CompiledAllowedMask(
        mask_id=_make_mask_id(ir.manifest.pack_id, modality),
        pack_id=ir.manifest.pack_id,
        artifact_family=ir.manifest.artifact_family,
        role_id=ir.manifest.role_id,
        modality=modality,
        allowed_field_ids=allowed_field_ids,
        allowed_claim_family_ids=allowed_claim_family_ids,
        allowed_review_rule_ids=allowed_review_rule_ids,
        allowed_projection_rule_ids=allowed_projection_rule_ids,
        denied_field_ids=denied_field_ids,
        denied_claim_family_ids=denied_claim_family_ids,
        denied_review_rule_ids=denied_review_rule_ids,
        denied_projection_rule_ids=denied_projection_rule_ids,
        mask_source_kind=mask_source_kind,
        fallback_used=fallback_used,
        source_paths=source_paths,
        source_hashes=source_hashes,
        slice_fingerprint=_slice_fingerprint(
            allowed_field_ids,
            allowed_claim_family_ids,
            allowed_review_rule_ids,
            allowed_projection_rule_ids,
        ),
    )
    _validate_mask_integrity(mask, review_rule_table, projection_rule_table, modality)
    return mask


def _validate_mask_integrity(
    mask: CompiledAllowedMask,
    review_rule_table: CompiledReviewRuleTable,
    projection_rule_table: CompiledProjectionRuleTable,
    modality: str,
) -> None:
    denied_field_set = set(mask.denied_field_ids)
    denied_claim_set = set(mask.denied_claim_family_ids)
    for projection_id in mask.allowed_projection_rule_ids:
        row = projection_rule_table.by_projection_rule_id[projection_id]
        if row.source_claim_family_id in denied_claim_set:
            raise ContractLoadError(
                f"Mask {mask.mask_id} allows projection {projection_id} with denied source claim "
                f"{row.source_claim_family_id}"
            )
        if any(target in denied_field_set for target in row.target_field_ids):
            raise ContractLoadError(
                f"Mask {mask.mask_id} allows projection {projection_id} with denied target field IDs"
            )

    allowed_field_set = set(mask.allowed_field_ids)
    allowed_claim_set = set(mask.allowed_claim_family_ids)
    for rule_id in mask.allowed_review_rule_ids:
        row = review_rule_table.by_rule_id[rule_id]
        has_allowed_field = any(field_id in allowed_field_set for field_id in row.applies_to_field_ids)
        has_allowed_claim = any(claim_id in allowed_claim_set for claim_id in row.applies_to_claim_family_ids)
        targets_modality = modality in row.applies_to_modalities
        if not (has_allowed_field or has_allowed_claim or targets_modality or _is_global_rule(row)):
            raise ContractLoadError(
                f"Mask {mask.mask_id} allows review rule {rule_id} that only targets denied slices"
            )


def _build_diagnostics(masks: tuple[CompiledAllowedMask, ...]) -> tuple[AllowedMaskDiagnostic, ...]:
    diagnostics: list[AllowedMaskDiagnostic] = []
    for mask in masks:
        is_empty = not (
            mask.allowed_field_ids
            or mask.allowed_claim_family_ids
            or mask.allowed_review_rule_ids
            or mask.allowed_projection_rule_ids
        )
        if is_empty:
            diagnostics.append(
                AllowedMaskDiagnostic(
                    level="warning",
                    code="allowed_masks.empty_mask",
                    message="Allowed mask has no allowed IDs across all substrate sets.",
                    mask_id=mask.mask_id,
                )
            )
        if not mask.allowed_claim_family_ids:
            diagnostics.append(
                AllowedMaskDiagnostic(
                    level="warning",
                    code="allowed_masks.claim_families_empty",
                    message="Allowed mask has zero claim families.",
                    mask_id=mask.mask_id,
                )
            )
        if not mask.allowed_projection_rule_ids:
            diagnostics.append(
                AllowedMaskDiagnostic(
                    level="warning",
                    code="allowed_masks.projection_rules_empty",
                    message="Allowed mask has zero projection rules.",
                    mask_id=mask.mask_id,
                )
            )
        if not mask.allowed_review_rule_ids:
            diagnostics.append(
                AllowedMaskDiagnostic(
                    level="warning",
                    code="allowed_masks.review_rules_empty",
                    message="Allowed mask has zero review rules.",
                    mask_id=mask.mask_id,
                )
            )
        if mask.fallback_used:
            diagnostics.append(
                AllowedMaskDiagnostic(
                    level="info",
                    code="allowed_masks.fallback_used",
                    message="Fallback semantics were involved in mask construction.",
                    mask_id=mask.mask_id,
                )
            )
    return tuple(diagnostics)


def _build_summary(masks: tuple[CompiledAllowedMask, ...]) -> AllowedMaskSummary:
    masks_by_modality: dict[str, int] = defaultdict(int)
    allowed_field_counts_by_modality: dict[str, int] = {}
    allowed_claim_counts_by_modality: dict[str, int] = {}
    allowed_rule_counts_by_modality: dict[str, int] = {}
    allowed_projection_counts_by_modality: dict[str, int] = {}
    empty_masks: list[str] = []
    fallback_masks: list[str] = []

    for mask in masks:
        masks_by_modality[mask.modality] += 1
        allowed_field_counts_by_modality[mask.modality] = len(mask.allowed_field_ids)
        allowed_claim_counts_by_modality[mask.modality] = len(mask.allowed_claim_family_ids)
        allowed_rule_counts_by_modality[mask.modality] = len(mask.allowed_review_rule_ids)
        allowed_projection_counts_by_modality[mask.modality] = len(mask.allowed_projection_rule_ids)
        if not (
            mask.allowed_field_ids
            or mask.allowed_claim_family_ids
            or mask.allowed_review_rule_ids
            or mask.allowed_projection_rule_ids
        ):
            empty_masks.append(mask.mask_id)
        if mask.fallback_used:
            fallback_masks.append(mask.mask_id)

    return AllowedMaskSummary(
        total_masks=len(masks),
        masks_by_modality=MappingProxyType(dict(sorted(masks_by_modality.items()))),
        allowed_field_counts_by_modality=MappingProxyType(dict(sorted(allowed_field_counts_by_modality.items()))),
        allowed_claim_family_counts_by_modality=MappingProxyType(dict(sorted(allowed_claim_counts_by_modality.items()))),
        allowed_review_rule_counts_by_modality=MappingProxyType(dict(sorted(allowed_rule_counts_by_modality.items()))),
        allowed_projection_rule_counts_by_modality=MappingProxyType(dict(sorted(allowed_projection_counts_by_modality.items()))),
        empty_masks=tuple(sorted(empty_masks)),
        masks_using_fallback=tuple(sorted(fallback_masks)),
    )


def to_jsonable_mask(mask: CompiledAllowedMask) -> dict[str, Any]:
    return {
        "mask_id": mask.mask_id,
        "pack_id": mask.pack_id,
        "artifact_family": mask.artifact_family,
        "role_id": mask.role_id,
        "modality": mask.modality,
        "allowed_field_ids": list(mask.allowed_field_ids),
        "allowed_claim_family_ids": list(mask.allowed_claim_family_ids),
        "allowed_review_rule_ids": list(mask.allowed_review_rule_ids),
        "allowed_projection_rule_ids": list(mask.allowed_projection_rule_ids),
        "denied_field_ids": list(mask.denied_field_ids),
        "denied_claim_family_ids": list(mask.denied_claim_family_ids),
        "denied_review_rule_ids": list(mask.denied_review_rule_ids),
        "denied_projection_rule_ids": list(mask.denied_projection_rule_ids),
        "mask_source_kind": mask.mask_source_kind,
        "fallback_used": mask.fallback_used,
        "source_paths": list(mask.source_paths),
        "source_hashes": list(mask.source_hashes),
        "slice_fingerprint": mask.slice_fingerprint,
    }


def to_jsonable_summary(summary: AllowedMaskSummary) -> dict[str, Any]:
    return {
        "total_masks": summary.total_masks,
        "masks_by_modality": dict(summary.masks_by_modality),
        "allowed_field_counts_by_modality": dict(summary.allowed_field_counts_by_modality),
        "allowed_claim_family_counts_by_modality": dict(summary.allowed_claim_family_counts_by_modality),
        "allowed_review_rule_counts_by_modality": dict(summary.allowed_review_rule_counts_by_modality),
        "allowed_projection_rule_counts_by_modality": dict(summary.allowed_projection_rule_counts_by_modality),
        "empty_masks": list(summary.empty_masks),
        "masks_using_fallback": list(summary.masks_using_fallback),
    }


def to_jsonable_diagnostic(diag: AllowedMaskDiagnostic) -> dict[str, Any]:
    return {
        "level": diag.level,
        "code": diag.code,
        "message": diag.message,
        "mask_id": diag.mask_id,
        "context": dict(diag.context),
    }


def compile_allowed_masks(
    ir: CanonicalIR,
    field_table: CompiledFieldTable,
    claim_table: CompiledClaimFamilyTable,
    review_rule_table: CompiledReviewRuleTable,
    projection_rule_table: CompiledProjectionRuleTable,
) -> CompiledAllowedMasks:
    _validate_inputs(ir, field_table, claim_table, review_rule_table, projection_rule_table)

    masks = tuple(
        sorted(
            (
                _build_mask(
                    ir,
                    field_table,
                    claim_table,
                    review_rule_table,
                    projection_rule_table,
                    modality,
                )
                for modality in sorted(ir.manifest.admitted_modalities)
            ),
            key=lambda mask: mask.mask_id,
        )
    )
    expected = set(ir.manifest.admitted_modalities)
    got = {mask.modality for mask in masks}
    if got != expected:
        missing = sorted(expected - got)
        raise ContractLoadError(f"Missing masks for admitted modalities: {missing}")
    diagnostics = _build_diagnostics(masks)
    summary = _build_summary(masks)

    return CompiledAllowedMasks(
        masks=masks,
        by_mask_id=MappingProxyType({mask.mask_id: mask for mask in masks}),
        by_modality=MappingProxyType({mask.modality: mask.mask_id for mask in masks}),
        diagnostics=diagnostics,
        summary=summary,
    )
