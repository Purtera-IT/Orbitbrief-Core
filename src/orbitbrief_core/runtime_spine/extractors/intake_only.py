from __future__ import annotations

from typing import Any, Iterable, Mapping

from .base import ExtractionResult


def _parsed_block_count(parsed: Any) -> int:
    blocks = getattr(parsed, "blocks", None)
    if isinstance(blocks, (list, tuple)):
        return len(blocks)
    spans = getattr(parsed, "evidence_spans", None)
    if isinstance(spans, (list, tuple)):
        return len(spans)
    return 0


def intake_only_result(role_id: str, modality: str, parsed: Any, reason: str) -> ExtractionResult:
    """Compatibility helper for legacy callers that expect ExtractionResult.

    The canonical runtime now routes non-claiming fallback through
    runtime_impl.run_intake_only_extractor(), but this helper remains importable
    for older modules and should never emit business claims.
    """

    review_flag: Mapping[str, Any] = {
        "code": "intake_only_lane",
        "severity": "high",
        "message": str(reason or "fallback_policy"),
        "claim_ids": [],
        "metadata": {
            "role_id": role_id,
            "modality": modality,
            "lane": "intake_only",
        },
    }
    return ExtractionResult(
        field_claims=[],
        review_flags=[review_flag],
        metadata={
            "parsed_block_count": _parsed_block_count(parsed),
            "lane": "intake_only",
            "role_id": role_id,
            "modality": modality,
        },
    )
