from __future__ import annotations

from dataclasses import dataclass, field

from orbitbrief_core.parser.site_schematic.vector_primitives import VectorPrimitive


@dataclass(frozen=True, slots=True)
class VectorJunction:
    junction_id: str
    x: float
    y: float
    primitive_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VectorPrimitiveGraph:
    page_index: int
    primitive_ids: tuple[str, ...] = ()
    junctions: tuple[VectorJunction, ...] = ()
    leader_candidate_ids: tuple[str, ...] = ()
    connector_candidate_ids: tuple[str, ...] = ()
    dimension_candidate_ids: tuple[str, ...] = ()
    diagnostics: dict[str, float] = field(default_factory=dict)


def build_vector_primitive_graph(primitives: tuple[VectorPrimitive, ...], *, page_index: int) -> VectorPrimitiveGraph:
    leader_ids: list[str] = []
    connector_ids: list[str] = []
    dimension_ids: list[str] = []
    for prim in primitives:
        bbox = prim.bbox
        if bbox is None:
            continue
        w = max(0.0, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        min_wh = min(w, h)
        long_ratio = max(w, h) / max(1.0, min_wh if min_wh > 0 else 1.0)
        if prim.primitive_kind == "line" and long_ratio >= 6:
            leader_ids.append(prim.primitive_id)
        if prim.primitive_kind in {"line", "polyline"} and long_ratio >= 3:
            connector_ids.append(prim.primitive_id)
        if prim.primitive_kind == "line" and 20 <= max(w, h) <= 300:
            dimension_ids.append(prim.primitive_id)
    diagnostics = {
        "primitive_count": float(len(primitives)),
        "leader_candidate_count": float(len(leader_ids)),
        "connector_candidate_count": float(len(connector_ids)),
        "dimension_candidate_count": float(len(dimension_ids)),
    }
    return VectorPrimitiveGraph(
        page_index=page_index,
        primitive_ids=tuple(prim.primitive_id for prim in primitives),
        leader_candidate_ids=tuple(leader_ids),
        connector_candidate_ids=tuple(connector_ids),
        dimension_candidate_ids=tuple(dimension_ids),
        diagnostics=diagnostics,
    )
