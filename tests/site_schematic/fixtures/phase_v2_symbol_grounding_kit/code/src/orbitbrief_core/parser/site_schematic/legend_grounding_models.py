from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

@dataclass
class LegendGroundingEntry:
    legend_id: str
    page_index: int
    family: str
    raw_label: str
    aliases: List[str] = field(default_factory=list)
    source_row_id: str = ""
    source_cell_ids: List[str] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None
    confidence: float = 0.0

@dataclass
class GroundedSymbol:
    grounded_id: str
    page_index: int
    candidate_id: str
    family: str
    semantic_meaning: str
    bbox: Optional[Tuple[float, float, float, float]]
    legend_ids: List[str] = field(default_factory=list)
    supporting_text_hints: List[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "grounded"
    metadata: Dict[str, Any] = field(default_factory=dict)
