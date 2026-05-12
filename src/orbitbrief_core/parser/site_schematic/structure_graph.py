from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from orbitbrief_core.parser.site_schematic.vector_primitive_graph import build_vector_primitive_graph

BBox = tuple[float, float, float, float]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _to_bbox(value: Any) -> BBox | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except Exception:
            return None
    return None


def _bbox_center(bbox: BBox) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _bbox_width(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _bbox_overlap_y(a: BBox, b: BBox) -> float:
    ay0, ay1 = a[1], a[3]
    by0, by1 = b[1], b[3]
    inter = max(0.0, min(ay1, by1) - max(ay0, by0))
    denom = max(1e-6, min(ay1 - ay0, by1 - by0))
    return inter / denom


@dataclass(slots=True)
class StructureNode:
    node_id: str
    node_kind: str
    bbox: BBox | None = None
    label: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StructureEdge:
    src_id: str
    dst_id: str
    edge_kind: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PageStructureGraph:
    page_index: int
    sheet_type: str
    nodes: list[StructureNode] = field(default_factory=list)
    edges: list[StructureEdge] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: StructureNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge: StructureEdge) -> None:
        self.edges.append(edge)

    def nodes_by_kind(self, node_kind: str) -> list[StructureNode]:
        return [n for n in self.nodes if n.node_kind == node_kind]


@dataclass(slots=True)
class ColumnLane:
    column_id: str
    bbox: BBox
    block_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0


def infer_columns_from_blocks(
    blocks: Iterable[Any],
    page_width: float,
    min_column_width_ratio: float = 0.18,
    gutter_ratio: float = 0.04,
) -> list[ColumnLane]:
    block_records = []
    for idx, block in enumerate(blocks):
        bbox = _to_bbox(_get(block, "bbox"))
        if not bbox:
            continue
        block_records.append(
            {
                "id": _get(block, "block_id", f"blk:{idx}"),
                "bbox": bbox,
                "center": _bbox_center(bbox),
            }
        )

    if not block_records or page_width <= 0:
        return []

    block_records.sort(key=lambda r: r["center"][0])
    gutter_px = max(page_width * gutter_ratio, 12.0)

    clusters: list[list[dict[str, Any]]] = []
    for rec in block_records:
        if not clusters:
            clusters.append([rec])
            continue
        prev_cluster = clusters[-1]
        prev_centers = [r["center"][0] for r in prev_cluster]
        prev_mean = sum(prev_centers) / len(prev_centers)
        if abs(rec["center"][0] - prev_mean) <= gutter_px * 2.5:
            prev_cluster.append(rec)
        else:
            clusters.append([rec])

    lanes: list[ColumnLane] = []
    min_col_width = page_width * min_column_width_ratio
    for i, cluster in enumerate(clusters):
        xs0 = [r["bbox"][0] for r in cluster]
        ys0 = [r["bbox"][1] for r in cluster]
        xs1 = [r["bbox"][2] for r in cluster]
        ys1 = [r["bbox"][3] for r in cluster]
        bbox = (min(xs0), min(ys0), max(xs1), max(ys1))
        if _bbox_width(bbox) < min_col_width and len(cluster) < 2:
            continue
        confidence = min(1.0, 0.45 + 0.08 * len(cluster))
        lanes.append(
            ColumnLane(
                column_id=f"col:{i+1}",
                bbox=bbox,
                block_ids=[r["id"] for r in cluster],
                confidence=confidence,
            )
        )
    return lanes


def build_page_structure_graph(
    *,
    page_index: int,
    sheet_type: str,
    layout_blocks: Iterable[Any],
    universal_tables: Iterable[Any],
    regions: Iterable[Any],
    detail_regions: Iterable[Any] | None = None,
    subregions: Iterable[Any] | None = None,
    pseudo_pages: Iterable[Any] | None = None,
    vector_primitives: Iterable[Any] | None = None,
    symbol_candidate_groups: Iterable[Any] | None = None,
    grounded_symbols: Iterable[Any] | None = None,
    page_width: float = 1000.0,
) -> PageStructureGraph:
    graph = PageStructureGraph(page_index=page_index, sheet_type=sheet_type)

    block_nodes: list[StructureNode] = []
    for idx, block in enumerate(layout_blocks):
        bbox = _to_bbox(_get(block, "bbox"))
        text = (_get(block, "text", "") or "").strip()
        kind = _get(block, "kind", "layout_block")
        node = StructureNode(
            node_id=_get(block, "block_id", f"blk:{page_index}:{idx}"),
            node_kind=kind,
            bbox=bbox,
            label=text[:120],
            confidence=float(_get(block, "confidence", 0.0) or 0.0),
            metadata={"text": text},
        )
        graph.add_node(node)
        block_nodes.append(node)

    lanes = infer_columns_from_blocks(layout_blocks, page_width=page_width)
    for lane in lanes:
        graph.add_node(
            StructureNode(
                node_id=lane.column_id,
                node_kind="column_lane",
                bbox=lane.bbox,
                confidence=lane.confidence,
                metadata={"block_ids": lane.block_ids},
            )
        )
        for block_id in lane.block_ids:
            graph.add_edge(
                StructureEdge(
                    src_id=block_id,
                    dst_id=lane.column_id,
                    edge_kind="in_column",
                    confidence=lane.confidence,
                )
            )

    for t_idx, table in enumerate(universal_tables):
        t_id = _get(table, "table_id", f"tbl:{page_index}:{t_idx}")
        t_bbox = _to_bbox(_get(table, "bbox"))
        table_kind = _get(table, "table_kind", "table")
        graph.add_node(
            StructureNode(
                node_id=t_id,
                node_kind="table",
                bbox=t_bbox,
                label=table_kind,
                confidence=float(_get(table, "confidence", 0.0) or 0.0),
                metadata={"table_kind": table_kind, "source_mode": _get(table, "source_mode", "")},
            )
        )
        for row_idx, row in enumerate(_get(table, "rows", []) or []):
            row_id = _get(row, "row_id", f"{t_id}:row:{row_idx}")
            row_bbox = _to_bbox(_get(row, "bbox"))
            graph.add_node(
                StructureNode(
                    node_id=row_id,
                    node_kind="table_row",
                    bbox=row_bbox,
                    confidence=float(_get(row, "confidence", 0.0) or 0.0),
                    metadata={"table_id": t_id, "row_index": _get(row, "row_index", row_idx)},
                )
            )
            graph.add_edge(StructureEdge(src_id=row_id, dst_id=t_id, edge_kind="row_in_table", confidence=1.0))
            for cell_idx, cell in enumerate(_get(row, "cells", []) or []):
                cell_id = _get(cell, "cell_id", f"{row_id}:cell:{cell_idx}")
                cell_bbox = _to_bbox(_get(cell, "bbox"))
                graph.add_node(
                    StructureNode(
                        node_id=cell_id,
                        node_kind="table_cell",
                        bbox=cell_bbox,
                        label=(_get(cell, "text", _get(cell, "raw_text", "")) or "")[:120],
                        confidence=float(_get(cell, "confidence", 0.0) or 0.0),
                        metadata={"table_id": t_id, "row_id": row_id, "col_index": _get(cell, "col_index", cell_idx)},
                    )
                )
                graph.add_edge(StructureEdge(src_id=cell_id, dst_id=row_id, edge_kind="cell_in_row", confidence=1.0))

    def _add_region_nodes(objs: Iterable[Any] | None, kind_name: str) -> None:
        if not objs:
            return
        for idx, obj in enumerate(objs):
            rid = _get(
                obj,
                "region_id",
                _get(
                    obj,
                    "detail_region_id",
                    _get(obj, "subregion_id", _get(obj, "pseudo_page_id", f"{kind_name}:{page_index}:{idx}")),
                ),
            )
            bbox = _to_bbox(_get(obj, "bbox"))
            label = _get(obj, "region_kind", _get(obj, "subregion_role", _get(obj, "pseudo_page_kind", kind_name)))
            graph.add_node(
                StructureNode(
                    node_id=rid,
                    node_kind=kind_name,
                    bbox=bbox,
                    label=str(label),
                    confidence=float(_get(obj, "confidence", 0.0) or 0.0),
                    metadata={"kind_label": label},
                )
            )

    _add_region_nodes(regions, "region")
    _add_region_nodes(detail_regions, "detail_region")
    _add_region_nodes(subregions, "subregion")
    _add_region_nodes(pseudo_pages, "pseudo_page")

    vector_prims = list(vector_primitives or [])
    vector_graph = None
    if vector_prims:
        vector_graph = build_vector_primitive_graph(tuple(vector_prims), page_index=page_index)
        for idx, prim in enumerate(vector_prims):
            prim_id = _get(prim, "primitive_id", f"vector_primitive:{page_index}:{idx}")
            prim_kind = _get(prim, "primitive_kind", "polyline")
            prim_bbox = _to_bbox(_get(prim, "bbox"))
            graph.add_node(
                StructureNode(
                    node_id=prim_id,
                    node_kind="vector_primitive",
                    bbox=prim_bbox,
                    label=str(prim_kind),
                    confidence=float(_get(prim, "confidence", 0.0) or 0.0),
                    metadata={
                        "primitive_kind": prim_kind,
                        "source_mode": _get(prim, "source_mode", ""),
                        "provider": _get(prim, "provider", ""),
                    },
                )
            )
            for region in (
                graph.nodes_by_kind("region")
                + graph.nodes_by_kind("detail_region")
                + graph.nodes_by_kind("subregion")
                + graph.nodes_by_kind("pseudo_page")
            ):
                if prim_bbox is None or region.bbox is None:
                    continue
                if _bbox_overlap_y(prim_bbox, region.bbox) >= 0.5:
                    graph.add_edge(
                        StructureEdge(
                            src_id=prim_id,
                            dst_id=region.node_id,
                            edge_kind="vector_in_region",
                            confidence=min(1.0, max(0.3, float(_get(prim, "confidence", 0.0) or 0.0))),
                        )
                    )

    v2_candidate_rows = list(symbol_candidate_groups or [])
    for idx, row in enumerate(v2_candidate_rows):
        node_id = _get(row, "candidate_id", f"v2_candidate:{page_index}:{idx}")
        bbox = _to_bbox(_get(row, "bbox"))
        graph.add_node(
            StructureNode(
                node_id=node_id,
                node_kind="symbol_candidate_group",
                bbox=bbox,
                label="|".join(_get(row, "family_candidates", [])[:3]) if _get(row, "family_candidates", []) else "",
                confidence=float(_get(row, "confidence", 0.0) or 0.0),
                metadata={
                    "primitive_ids": list(_get(row, "primitive_ids", []) or []),
                    "text_hints": list(_get(row, "text_hints", []) or []),
                },
            )
        )

    v2_grounded_rows = list(grounded_symbols or [])
    for idx, row in enumerate(v2_grounded_rows):
        node_id = _get(row, "grounded_id", f"v2_grounded:{page_index}:{idx}")
        bbox = _to_bbox(_get(row, "bbox"))
        graph.add_node(
            StructureNode(
                node_id=node_id,
                node_kind="grounded_symbol",
                bbox=bbox,
                label=str(_get(row, "family", "")),
                confidence=float(_get(row, "confidence", 0.0) or 0.0),
                metadata={
                    "candidate_id": _get(row, "candidate_id", ""),
                    "status": _get(row, "status", ""),
                    "legend_ids": list(_get(row, "legend_ids", []) or []),
                },
            )
        )
        candidate_id = _get(row, "candidate_id", "")
        if candidate_id:
            graph.add_edge(
                StructureEdge(
                    src_id=node_id,
                    dst_id=candidate_id,
                    edge_kind="grounded_from_candidate",
                    confidence=float(_get(row, "confidence", 0.0) or 0.0),
                )
            )

    for node in block_nodes + graph.nodes_by_kind("table"):
        if not node.bbox:
            continue
        for region in (
            graph.nodes_by_kind("region")
            + graph.nodes_by_kind("detail_region")
            + graph.nodes_by_kind("subregion")
            + graph.nodes_by_kind("pseudo_page")
            + graph.nodes_by_kind("column_lane")
        ):
            if not region.bbox:
                continue
            if _bbox_overlap_y(node.bbox, region.bbox) >= 0.5:
                graph.add_edge(
                    StructureEdge(
                        src_id=node.node_id,
                        dst_id=region.node_id,
                        edge_kind="inside_region",
                        confidence=min(1.0, max(node.confidence, region.confidence)),
                    )
                )

    graph.diagnostics = {
        "column_count": len(lanes),
        "table_count": len(graph.nodes_by_kind("table")),
        "region_count": len(graph.nodes_by_kind("region")),
        "detail_region_count": len(graph.nodes_by_kind("detail_region")),
        "subregion_count": len(graph.nodes_by_kind("subregion")),
        "pseudo_page_count": len(graph.nodes_by_kind("pseudo_page")),
        "vector_primitive_count": len(vector_prims),
        "vector_graph_constructed": bool(vector_graph),
        "vector_leader_candidate_count": int(vector_graph.diagnostics.get("leader_candidate_count", 0.0)) if vector_graph else 0,
        "vector_connector_candidate_count": int(vector_graph.diagnostics.get("connector_candidate_count", 0.0)) if vector_graph else 0,
        "vector_dimension_candidate_count": int(vector_graph.diagnostics.get("dimension_candidate_count", 0.0)) if vector_graph else 0,
        "v2_candidate_group_count": len(v2_candidate_rows),
        "v2_grounded_symbol_count": len(v2_grounded_rows),
        "symbol_candidate_group_count": len(v2_candidate_rows),
        "grounded_symbol_count": len(v2_grounded_rows),
    }
    return graph
