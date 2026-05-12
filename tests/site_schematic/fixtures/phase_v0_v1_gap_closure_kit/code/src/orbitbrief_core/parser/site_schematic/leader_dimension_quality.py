from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from orbitbrief_core.parser.site_schematic.vector_primitives import VectorPrimitive


@dataclass
class SemanticQuality:
    primitive_id: str
    score: float
    valid: bool
    reasons: List[str]


def _dims(bbox: Optional[Tuple[float, float, float, float]]) -> Tuple[float, float]:
    if bbox is None:
        return 0.0, 0.0
    return max(0.0, bbox[2] - bbox[0]), max(0.0, bbox[3] - bbox[1])


def score_leader_semantic_quality(p: VectorPrimitive, *, nearby_text_hint: bool = False) -> SemanticQuality:
    reasons: List[str] = []
    w, h = _dims(p.bbox)
    aspect = max(w, h) / max(1.0, min(w, h) if min(w, h) > 0 else 1.0)
    score = 0.4
    if p.primitive_kind in {"line", "polyline"}:
        if aspect >= 6:
            score += 0.35
            reasons.append("high_aspect")
        elif aspect >= 3:
            score += 0.2
            reasons.append("moderate_aspect")
    if max(w, h) >= 25:
        score += 0.15
        reasons.append("minimum_length")
    if nearby_text_hint:
        score += 0.15
        reasons.append("nearby_text_hint")
    return SemanticQuality(p.primitive_id, score, score >= 0.75, reasons)


def score_dimension_semantic_quality(
    p: VectorPrimitive,
    *,
    nearby_numeric_text: bool = False,
    witness_line_hint: bool = False,
) -> SemanticQuality:
    reasons: List[str] = []
    w, h = _dims(p.bbox)
    aspect = max(w, h) / max(1.0, min(w, h) if min(w, h) > 0 else 1.0)
    score = 0.35
    if p.primitive_kind in {"line", "polyline"} and aspect >= 4:
        score += 0.25
        reasons.append("dimension_like_aspect")
    if max(w, h) >= 20:
        score += 0.1
        reasons.append("dimension_length")
    if nearby_numeric_text:
        score += 0.2
        reasons.append("nearby_numeric_text")
    if witness_line_hint:
        score += 0.15
        reasons.append("witness_line_hint")
    return SemanticQuality(p.primitive_id, score, score >= 0.75, reasons)
