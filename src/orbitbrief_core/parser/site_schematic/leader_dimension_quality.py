from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.site_schematic.vector_primitives import VectorPrimitive


@dataclass(frozen=True, slots=True)
class SemanticQuality:
    primitive_id: str
    score: float
    valid: bool
    reasons: tuple[str, ...]


def _dims(bbox: tuple[float, float, float, float] | None) -> tuple[float, float]:
    if bbox is None:
        return (0.0, 0.0)
    return (max(0.0, bbox[2] - bbox[0]), max(0.0, bbox[3] - bbox[1]))


def score_leader_semantic_quality(
    primitive: VectorPrimitive,
    *,
    nearby_text_hint: bool = False,
) -> SemanticQuality:
    reasons: list[str] = []
    width, height = _dims(primitive.bbox)
    min_wh = min(width, height)
    aspect = max(width, height) / max(1.0, min_wh if min_wh > 0 else 1.0)
    score = 0.4
    if primitive.primitive_kind in {"line", "polyline"}:
        if aspect >= 6:
            score += 0.35
            reasons.append("high_aspect")
        elif aspect >= 3:
            score += 0.2
            reasons.append("moderate_aspect")
    if max(width, height) >= 25:
        score += 0.15
        reasons.append("minimum_length")
    if nearby_text_hint:
        score += 0.15
        reasons.append("nearby_text_hint")
    return SemanticQuality(
        primitive_id=primitive.primitive_id,
        score=score,
        valid=score >= 0.75,
        reasons=tuple(reasons),
    )


def score_dimension_semantic_quality(
    primitive: VectorPrimitive,
    *,
    nearby_numeric_text: bool = False,
    witness_line_hint: bool = False,
) -> SemanticQuality:
    reasons: list[str] = []
    width, height = _dims(primitive.bbox)
    min_wh = min(width, height)
    aspect = max(width, height) / max(1.0, min_wh if min_wh > 0 else 1.0)
    score = 0.35
    if primitive.primitive_kind in {"line", "polyline"} and aspect >= 4:
        score += 0.25
        reasons.append("dimension_like_aspect")
    if max(width, height) >= 20:
        score += 0.1
        reasons.append("dimension_length")
    if nearby_numeric_text:
        score += 0.2
        reasons.append("nearby_numeric_text")
    if witness_line_hint:
        score += 0.15
        reasons.append("witness_line_hint")
    return SemanticQuality(
        primitive_id=primitive.primitive_id,
        score=score,
        valid=score >= 0.75,
        reasons=tuple(reasons),
    )
