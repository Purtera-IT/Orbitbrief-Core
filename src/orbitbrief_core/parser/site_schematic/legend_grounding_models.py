from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class LegendGroundingEntry:
    legend_id: str
    page_index: int
    family: str
    raw_label: str
    aliases: tuple[str, ...] = ()
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    bbox: BBox | None = None
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class GroundedSymbol:
    grounded_id: str
    page_index: int
    candidate_id: str
    family: str
    semantic_meaning: str
    bbox: BBox | None
    legend_ids: tuple[str, ...] = ()
    supporting_text_hints: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "grounded"
    metadata: dict[str, Any] = field(default_factory=dict)
