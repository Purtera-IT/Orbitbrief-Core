from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProviderLayoutBlock:
    block_id: str
    page_index: int
    bbox: tuple[float, float, float, float] | None
    text: str
    role: str
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderTableRegion:
    region_id: str
    page_index: int
    bbox: tuple[float, float, float, float] | None
    text: str
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderPdfHypothesis:
    hypothesis_id: str
    source: str
    page_blocks: tuple[ProviderLayoutBlock, ...]
    table_regions: tuple[ProviderTableRegion, ...] = ()
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
