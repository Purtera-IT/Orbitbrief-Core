from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from orbitbrief_core.runtime_spine.extractors.registry import ExtractorRegistry, ExtractorRegistryError, ExtractorSpec

PipelineState = Literal["extract", "intake_only", "parked", "unsupported"]


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    state: PipelineState
    reason_codes: tuple[str, ...]
    extractor_spec: ExtractorSpec | None
    emits_business_claims: bool
    review_required: bool


def decide_pipeline_state(
    *,
    extractor_registry: ExtractorRegistry,
    role_id: str,
    modality: str,
    discourse_type: str,
    routing_confidence: float,
    packet_count: int = 0,
    weak_ocr: bool = False,
    template_schema_artifact: bool = False,
    meta_reference_artifact: bool = False,
    min_extract_confidence: float = 0.40,
    min_packet_count: int = 0,
) -> PipelineDecision:
    if template_schema_artifact:
        try:
            fallback = extractor_registry.resolve(
                role_id=role_id,
                modality=modality,
                discourse_type=discourse_type,
                allow_intake_only_fallback=True,
            )
        except ExtractorRegistryError:
            fallback = None
        return PipelineDecision(
            state="intake_only",
            reason_codes=("template_schema_artifact",),
            extractor_spec=fallback if fallback is not None and fallback.kind == "intake_only" else None,
            emits_business_claims=False,
            review_required=True,
        )

    if meta_reference_artifact:
        try:
            fallback = extractor_registry.resolve(
                role_id=role_id,
                modality=modality,
                discourse_type=discourse_type,
                allow_intake_only_fallback=True,
            )
        except ExtractorRegistryError:
            fallback = None
        return PipelineDecision(
            state="intake_only",
            reason_codes=("meta_reference_artifact",),
            extractor_spec=fallback if fallback is not None and fallback.kind == "intake_only" else None,
            emits_business_claims=False,
            review_required=True,
        )

    if weak_ocr:
        return PipelineDecision(
            state="parked",
            reason_codes=("weak_ocr",),
            extractor_spec=None,
            emits_business_claims=False,
            review_required=True,
        )

    if packet_count < min_packet_count:
        return PipelineDecision(
            state="parked",
            reason_codes=("insufficient_evidence",),
            extractor_spec=None,
            emits_business_claims=False,
            review_required=True,
        )

    if routing_confidence < min_extract_confidence:
        return PipelineDecision(
            state="parked",
            reason_codes=("parse_confidence_too_low",),
            extractor_spec=None,
            emits_business_claims=False,
            review_required=True,
        )

    try:
        primary = extractor_registry.resolve(
            role_id=role_id,
            modality=modality,
            discourse_type=discourse_type,
            allow_intake_only_fallback=False,
        )
        return PipelineDecision(
            state="extract",
            reason_codes=(),
            extractor_spec=primary,
            emits_business_claims=primary.emits_business_claims,
            review_required=False,
        )
    except ExtractorRegistryError as exc:
        reason_codes = _derive_reason_codes(
            extractor_registry=extractor_registry,
            role_id=role_id,
            modality=modality,
            discourse_type=discourse_type,
            error=exc,
        )

    try:
        fallback = extractor_registry.resolve(
            role_id=role_id,
            modality=modality,
            discourse_type=discourse_type,
            allow_intake_only_fallback=True,
        )
        if fallback.kind == "intake_only":
            return PipelineDecision(
                state="intake_only",
                reason_codes=reason_codes,
                extractor_spec=fallback,
                emits_business_claims=False,
                review_required=True,
            )
    except ExtractorRegistryError as exc:
        message = str(exc).lower()
        if "ambiguous" in message:
            return PipelineDecision(
                state="unsupported",
                reason_codes=tuple(sorted(set(reason_codes + ("ambiguous_extractor_resolution",)))),
                extractor_spec=None,
                emits_business_claims=False,
                review_required=True,
            )

    return PipelineDecision(
        state="unsupported",
        reason_codes=reason_codes,
        extractor_spec=None,
        emits_business_claims=False,
        review_required=True,
    )


def _derive_reason_codes(
    *,
    extractor_registry: ExtractorRegistry,
    role_id: str,
    modality: str,
    discourse_type: str,
    error: Exception,
) -> tuple[str, ...]:
    enabled = extractor_registry.all_enabled()
    reason_codes: list[str] = []
    role_specs = [spec for spec in enabled if spec.role_id == role_id]
    if not role_specs:
        reason_codes.append("unsupported_role")
    else:
        modality_specs = [spec for spec in role_specs if modality in spec.supports_modalities]
        if not modality_specs:
            reason_codes.append("unsupported_modality")
        else:
            discourse_specs = [spec for spec in modality_specs if discourse_type in spec.supports_discourse_types]
            if not discourse_specs:
                reason_codes.append("unsupported_discourse_type")
    message = str(error).lower()
    if "ambiguous" in message:
        reason_codes.append("ambiguous_extractor_resolution")
    if "no enabled extractor" in message:
        reason_codes.append("no_registered_extractor")
    if not reason_codes:
        reason_codes.append("policy_blocked")
    return tuple(sorted(set(reason_codes)))
