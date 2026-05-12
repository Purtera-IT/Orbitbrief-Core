from __future__ import annotations

from typing import Any

from .narrative_extractor import run_narrative_extractor as _run_packet_bounded_narrative_extractor


def run_narrative_extractor(
    *,
    role_id: str,
    modality: str,
    packet_candidates: list[dict[str, Any]],
    compiled_runtime_policy: Any | None = None,
) -> dict[str, Any]:
    """Entrypoint retained for registry compatibility."""
    return _run_packet_bounded_narrative_extractor(
        role_id=role_id,
        modality=modality,
        packet_candidates=packet_candidates,
        compiled_runtime_policy=compiled_runtime_policy,
    )


def run_intake_only_extractor(
    *,
    role_id: str,
    modality: str,
    reason: str | None = None,
    reason_codes: tuple[str, ...] | list[str] | None = None,
    pipeline_state: str = "intake_only",
    packet_count: int = 0,
) -> dict[str, Any]:
    """Deterministic intake-only fallback result envelope."""
    reason_codes_tuple = tuple(reason_codes or ())
    return {
        "role_id": role_id,
        "modality": modality,
        "lane": pipeline_state,
        "reason": reason or "fallback_policy",
        "reason_codes": list(reason_codes_tuple),
        "packet_count": int(packet_count),
        "review_required": True,
        "field_claims": [],
        "emits_business_claims": False,
    }
