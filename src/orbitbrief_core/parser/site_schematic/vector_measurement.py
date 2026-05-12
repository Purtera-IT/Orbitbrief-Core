from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orbitbrief_core.parser.site_schematic.vector_primitive_graph import VectorPrimitiveGraph

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class MeasurementCandidate:
    measurement_id: str
    page_index: int
    bbox: BBox | None
    measurement_source: str  # vector | raster | inferred
    scale_source: str  # title_block | detail_scale | dimension_text | inferred
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


def build_measurement_candidates_from_vector_graph(
    graph: VectorPrimitiveGraph,
) -> tuple[MeasurementCandidate, ...]:
    candidates: list[MeasurementCandidate] = []
    for idx, primitive_id in enumerate(graph.dimension_candidate_ids, start=1):
        candidates.append(
            MeasurementCandidate(
                measurement_id=f"measure:p{graph.page_index}:{idx}",
                page_index=graph.page_index,
                bbox=None,
                measurement_source="vector",
                scale_source="inferred",
                confidence=0.72,
                metadata={"primitive_id": primitive_id},
            )
        )
    return tuple(candidates)
