from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _lower(s: str) -> str:
    return (s or "").strip().lower()


@dataclass(slots=True)
class SheetArchetypeHint:
    sheet_id_candidates: list[str] = field(default_factory=list)
    family_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


SHEET_FAMILY_KEYWORDS: dict[str, list[str]] = {
    "legend_symbol": ["legend", "symbols", "symbol list", "responsibility matrix"],
    "notes_spec": ["notes", "spec", "requirements", "general notes"],
    "drawing_index": ["drawing index", "sheet number", "sheet title"],
    "riser_diagram": ["riser", "conduit riser", "cabling riser", "matv cabling riser"],
    "equipment_room_layout": ["equipment room", "mdf", "idf", "rack details", "equipment rack"],
    "installation_detail": ["installation detail", "details", "security installation"],
    "floorplan_overall": ["floor plan", "overall", "part plans", "enlarged guestroom layouts"],
}


def build_sheet_archetype_hints(structure_graph: Any) -> SheetArchetypeHint:
    hint = SheetArchetypeHint()
    nodes = getattr(structure_graph, "nodes", [])
    text_pool: list[str] = []
    for node in nodes:
        label = _lower(getattr(node, "label", ""))
        meta_text = _lower((getattr(node, "metadata", {}) or {}).get("text", ""))
        if label:
            text_pool.append(label)
        if meta_text and meta_text not in text_pool:
            text_pool.append(meta_text)

    joined = " | ".join(text_pool)
    for piece in text_pool:
        for token in piece.replace("(", " ").replace(")", " ").replace("-", " ").split():
            raw = token.upper()
            if any(ch.isdigit() for ch in raw) and len(raw) >= 3 and raw not in hint.sheet_id_candidates:
                hint.sheet_id_candidates.append(raw)

    for family, keywords in SHEET_FAMILY_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            if kw in joined:
                score += 1.0
        if score:
            hint.family_scores[family] = score
            hint.reasons.append(f"{family}:keyword_match:{score}")

    if "riser_diagram" in hint.family_scores and "legend_symbol" in hint.family_scores:
        hint.family_scores["riser_diagram"] += 0.5
        hint.reasons.append("riser_before_legend_guard")
    if "floorplan_overall" in hint.family_scores and "drawing_index" in hint.family_scores:
        hint.family_scores["floorplan_overall"] += 0.25
        hint.reasons.append("floorplan_before_index_guard")
    return hint
