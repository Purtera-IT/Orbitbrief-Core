from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import FieldClaim, ReviewFlag
from ..parsers import ParsedArtifact


@dataclass(slots=True)
class ExtractionResult:
    field_claims: list[FieldClaim] = field(default_factory=list)
    review_flags: list[ReviewFlag] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Extractor:
    role_id: str
    supported_modalities: set[str]

    def extract(self, parsed: ParsedArtifact, schema_ref: str) -> ExtractionResult:
        raise NotImplementedError
