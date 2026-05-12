from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

BBox = Tuple[float, float, float, float]

@dataclass
class SymbolCandidateGroup:
    candidate_id: str
    page_index: int
    bbox: Optional[BBox]
    primitive_ids: List[str] = field(default_factory=list)
    text_hints: List[str] = field(default_factory=list)
    family_candidates: List[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

def group_symbol_candidates_from_primitives(
    *,
    page_index: int,
    vector_primitives: Iterable[Any],
    nearby_text_hints: Iterable[str] | None = None,
) -> List[SymbolCandidateGroup]:
    out: List[SymbolCandidateGroup] = []
    text_hints = list(nearby_text_hints or [])
    for idx, p in enumerate(vector_primitives):
        bbox = getattr(p, "bbox", None) if not isinstance(p, dict) else p.get("bbox")
        prim_id = getattr(p, "primitive_id", None) if not isinstance(p, dict) else p.get("primitive_id")
        kind = getattr(p, "primitive_kind", None) if not isinstance(p, dict) else p.get("primitive_kind")
        if bbox is None or prim_id is None:
            continue
        if kind == "box":
            family_candidates = ["telecom_rack_front", "pull_or_junction_box", "patch_panel_row"]
        elif kind == "line":
            family_candidates = ["conduit_pathway", "riser_endpoint", "unknown_symbol_group"]
        elif kind == "polyline":
            family_candidates = ["ladder_rack_runway", "conduit_pathway", "unknown_symbol_group"]
        else:
            family_candidates = ["unknown_symbol_group"]

        out.append(SymbolCandidateGroup(
            candidate_id=f"cand:{page_index}:{idx}",
            page_index=page_index,
            bbox=bbox,
            primitive_ids=[prim_id],
            text_hints=text_hints[:8],
            family_candidates=family_candidates,
            confidence=0.55,
            metadata={"seed_kind": kind},
        ))
    return out
