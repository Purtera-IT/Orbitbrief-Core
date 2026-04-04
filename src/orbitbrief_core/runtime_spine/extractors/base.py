from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(slots=True)
class ExtractionResult:
    """Compatibility extractor result envelope.

    Legacy runtime_spine helpers still import this symbol even though the
    canonical hot path now uses mapping-based extractor outputs plus the
    deterministic postprocess layer.
    """

    field_claims: list[Mapping[str, Any]] = field(default_factory=list)
    review_flags: list[Mapping[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Extractor(Protocol):
    role_id: str
    supported_modalities: set[str]

    def extract(self, parsed: Any, schema_ref: str) -> ExtractionResult:
        ...
