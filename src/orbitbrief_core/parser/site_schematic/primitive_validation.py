from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.site_schematic.vector_primitives import VectorPrimitive


@dataclass(frozen=True, slots=True)
class PrimitiveValidation:
    primitive_id: str
    valid: bool
    quality_score: float
    candidate_kind: str
    reasons: tuple[str, ...]


def _bbox_dims(bbox: tuple[float, float, float, float] | None) -> tuple[float, float]:
    if bbox is None:
        return (0.0, 0.0)
    return (max(0.0, bbox[2] - bbox[0]), max(0.0, bbox[3] - bbox[1]))


def validate_vector_primitive(primitive: VectorPrimitive) -> PrimitiveValidation:
    bbox = primitive.bbox
    if bbox is None:
        return PrimitiveValidation(
            primitive_id=primitive.primitive_id,
            valid=False,
            quality_score=0.0,
            candidate_kind="invalid",
            reasons=("missing_bbox",),
        )

    width, height = _bbox_dims(bbox)
    candidate_kind = primitive.primitive_kind
    reasons: list[str] = []
    score = 0.5

    if primitive.primitive_kind == "line":
        min_wh = min(width, height)
        long_ratio = max(width, height) / max(1.0, min_wh if min_wh > 0 else 1.0)
        if long_ratio >= 6:
            candidate_kind = "leader_or_connector"
            score = 0.9
            reasons.append("high_aspect_line")
        elif long_ratio >= 3:
            candidate_kind = "connector"
            score = 0.75
            reasons.append("moderate_aspect_line")
        else:
            candidate_kind = "short_line"
            score = 0.55
    elif primitive.primitive_kind == "box":
        candidate_kind = "box"
        score = 0.85
    elif primitive.primitive_kind == "polyline":
        candidate_kind = "polyline"
        score = 0.8
    elif primitive.primitive_kind == "curve":
        candidate_kind = "curve_or_circle"
        score = 0.6

    return PrimitiveValidation(
        primitive_id=primitive.primitive_id,
        valid=score >= 0.55,
        quality_score=score,
        candidate_kind=candidate_kind,
        reasons=tuple(reasons),
    )
