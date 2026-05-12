from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class NoteScopeDecision:
    scope_class: str
    locality_confidence: float
    reasons: list[str]
    locality_ids: dict[str, str]


STRUCTURAL_LOCAL = {"detail_region", "subregion", "pseudo_page"}
GLOBALISH = {"region"}


def infer_note_scope_with_structure_graph(
    note_block: Any,
    structure_graph: Any,
    *,
    detail_tokens: list[str] | None = None,
    prefer_column_local: bool = True,
) -> NoteScopeDecision:
    detail_tokens = detail_tokens or []
    if isinstance(note_block, dict):
        note_id = str(note_block.get("block_id") or note_block.get("region_id") or "note")
    else:
        note_id = getattr(note_block, "block_id", None) or getattr(note_block, "region_id", None) or "note"
    overlaps = []
    for edge in getattr(structure_graph, "edges", []):
        if getattr(edge, "src_id", None) == note_id and getattr(edge, "edge_kind", "") == "inside_region":
            overlaps.append(getattr(edge, "dst_id", None))
    nodes_by_id = {getattr(n, "node_id", None): n for n in getattr(structure_graph, "nodes", [])}

    locality_ids: dict[str, str] = {}
    reasons: list[str] = []
    structural_hits = []
    column_hits = []
    global_hits = []
    for oid in overlaps:
        node = nodes_by_id.get(oid)
        if not node:
            continue
        kind = getattr(node, "node_kind", "")
        if kind in STRUCTURAL_LOCAL:
            structural_hits.append(node)
        elif kind == "column_lane":
            column_hits.append(node)
        elif kind in GLOBALISH:
            global_hits.append(node)

    if structural_hits:
        best = structural_hits[0]
        locality_ids[best.node_kind] = best.node_id
        confidence = 0.9 if detail_tokens else 0.85
        reasons.append(f"structural_locality:{best.node_kind}")
        if detail_tokens:
            reasons.append("detail_tokens_present")
        return NoteScopeDecision("detail_local", min(confidence, 1.0), reasons, locality_ids)

    if column_hits and prefer_column_local:
        best = column_hits[0]
        locality_ids["column_id"] = best.node_id
        confidence = 0.75 if detail_tokens else 0.7
        reasons.append("column_locality")
        if detail_tokens:
            reasons.append("detail_tokens_present")
        return NoteScopeDecision("column_local", min(confidence, 1.0), reasons, locality_ids)

    if global_hits:
        locality_ids["region_id"] = global_hits[0].node_id
        reasons.append("page_global_fallback")
        return NoteScopeDecision("page_global", 0.6, reasons, locality_ids)

    reasons.append("unresolved_scope")
    return NoteScopeDecision("unresolved", 0.2, reasons, locality_ids)
