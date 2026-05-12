from __future__ import annotations

from typing import Iterable

from orbitbrief_core.parser.site_schematic.vector_primitives import VectorPrimitive


def _round_bbox(bbox: tuple[float, float, float, float] | None, ndigits: int = 4) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    return tuple(round(float(row), ndigits) for row in bbox)


def dedup_vector_primitives(primitives: Iterable[VectorPrimitive]) -> list[VectorPrimitive]:
    seen: dict[tuple[str, tuple[float, float, float, float] | None], int] = {}
    out: list[VectorPrimitive] = []
    for primitive in primitives:
        metadata = dict(primitive.metadata or {})
        key = (
            primitive.primitive_kind,
            _round_bbox(primitive.bbox, 4),
            str(metadata.get("raw_tag", "")),
            bool(metadata.get("fallback", False)),
        )
        if key in seen:
            prev_idx = seen[key]
            if primitive.confidence > out[prev_idx].confidence:
                out[prev_idx] = primitive
            continue
        seen[key] = len(out)
        out.append(primitive)
    return out
