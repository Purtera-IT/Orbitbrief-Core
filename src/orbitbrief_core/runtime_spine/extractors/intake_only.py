from __future__ import annotations

from .base import ExtractionResult
from ..contracts import ReviewFlag
from ..shared import make_id, utc_now
from ..parsers import ParsedArtifact


def intake_only_result(role_id: str, modality: str, parsed: ParsedArtifact, reason: str) -> ExtractionResult:
    return ExtractionResult(
        field_claims=[],
        review_flags=[
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="high",
                code="intake_only_lane",
                message=reason,
                requires_human=True,
                created_at=utc_now(),
            )
        ],
        metadata={"parsed_block_count": len(parsed.blocks), "lane": "intake_only"},
    )
