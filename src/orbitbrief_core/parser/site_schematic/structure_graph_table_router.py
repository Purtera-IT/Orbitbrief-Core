from __future__ import annotations

from typing import Any


def _lower(s: str) -> str:
    return (s or "").strip().lower()


TABLE_KIND_SIGNATURES: dict[str, list[list[str]]] = {
    "drawing_index": [["sheet", "title"], ["dwg", "drawing"], ["sheet number", "sheet title"]],
    "symbol_legend": [["symbol", "description"], ["cable count", "termination"], ["power", "remarks"]],
    "abbreviation_matrix": [["abbreviations"], ["abbr"], ["term"]],
    "outlet_definition": [["outlet", "description"], ["type", "termination"], ["mounting"]],
    "schedule": [["schedule"], ["description", "qty"], ["comments"]],
    "component_spec": [["description", "manufacturer", "part"], ["part number", "comments"]],
    "manufacturer_part_table": [["manufacturer", "part number"], ["description", "comments"]],
    "responsibility_matrix": [["responsibility matrix"], ["contractor"], ["provide"]],
}


def infer_table_kind_from_structure_graph(table: Any, structure_graph: Any) -> tuple[str, dict[str, float]]:
    _ = structure_graph
    rows = getattr(table, "rows", None) or (table.get("rows") if isinstance(table, dict) else []) or []
    texts: list[str] = []
    for row in rows[:6]:
        cells = getattr(row, "cells", None) or (row.get("cells") if isinstance(row, dict) else []) or []
        for cell in cells:
            txt = _lower(
                getattr(cell, "raw_text", None)
                or getattr(cell, "text", None)
                or (cell.get("raw_text") if isinstance(cell, dict) else "")
                or (cell.get("text") if isinstance(cell, dict) else "")
            )
            if txt:
                texts.append(txt)
    header_text = " | ".join(texts[:14])
    scores: dict[str, float] = {}
    for kind, sig_groups in TABLE_KIND_SIGNATURES.items():
        score = 0.0
        for group in sig_groups:
            if all(term in header_text for term in group):
                score += 2.0
            elif any(term in header_text for term in group):
                score += 0.5
        if "schedule" in header_text and kind in {"schedule", "component_spec"}:
            score += 1.0
        if score:
            scores[kind] = score

    if not scores:
        return "generic_grid", {"generic_grid": 1.0}
    best = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return best, scores
