from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def _lower(s: str) -> str:
    return (s or "").strip().lower()


HOLDOUT_TABLE_SIGNATURES = {
    "drawing_index": [
        ["sheet number", "sheet title"],
        ["dwg", "drawing"],
        ["sheet", "title", "count"],
    ],
    "symbol_legend": [
        ["symbol", "description"],
        ["cable count", "termination"],
        ["power", "remarks"],
    ],
    "abbreviation_matrix": [
        ["abbreviations"],
        ["abbr"],
        ["term"],
    ],
    "outlet_definition": [
        ["outlet", "description"],
        ["outlet type", "description"],
        ["mounting", "termination"],
    ],
    "schedule": [
        ["schedule"],
        ["description", "qty"],
        ["comments"],
    ],
    "component_spec": [
        ["description", "manufacturer", "part"],
        ["part number", "comments"],
    ],
    "manufacturer_part_table": [
        ["manufacturer", "part number"],
        ["description", "comments"],
    ],
    "responsibility_matrix": [
        ["responsibility matrix"],
        ["provide", "install"],
    ],
}


def score_holdout_table_family(
    header_text: str,
    cell_texts: Iterable[str],
    *,
    sheet_family_hint: str = "",
    region_kind_hint: str = "",
) -> Dict[str, float]:
    header_text = _lower(header_text)
    cell_join = " | ".join(_lower(x) for x in cell_texts)
    combined = header_text + " | " + cell_join
    scores: Dict[str, float] = {}

    for kind, sigs in HOLDOUT_TABLE_SIGNATURES.items():
        score = 0.0
        for sig in sigs:
            if all(tok in combined for tok in sig):
                score += 2.0
            elif any(tok in combined for tok in sig):
                score += 0.5
        if kind == "drawing_index" and "sheet" in combined and "title" in combined:
            score += 1.0
        if kind == "symbol_legend" and "legend" in combined:
            score += 1.0
        if kind == "schedule" and "schedule" in combined:
            score += 1.0
        if kind == "responsibility_matrix" and "responsibility" in combined:
            score += 1.5
        if score:
            scores[kind] = score

    # priors
    sf = _lower(sheet_family_hint)
    rk = _lower(region_kind_hint)
    if "legend" in sf:
        scores["symbol_legend"] = scores.get("symbol_legend", 0.0) + 0.75
        scores["responsibility_matrix"] = scores.get("responsibility_matrix", 0.0) + 0.35
    if "notes" in sf or "spec" in sf:
        scores["drawing_index"] = scores.get("drawing_index", 0.0) + 0.25
        scores["schedule"] = scores.get("schedule", 0.0) + 0.25
    if "schedule" in rk:
        scores["schedule"] = scores.get("schedule", 0.0) + 0.5
    if "legend" in rk:
        scores["symbol_legend"] = scores.get("symbol_legend", 0.0) + 0.5

    return scores


def choose_holdout_table_family(
    header_text: str,
    cell_texts: Iterable[str],
    *,
    sheet_family_hint: str = "",
    region_kind_hint: str = "",
) -> Tuple[str, Dict[str, float]]:
    scores = score_holdout_table_family(
        header_text, cell_texts, sheet_family_hint=sheet_family_hint, region_kind_hint=region_kind_hint
    )
    if not scores:
        return "generic_grid", {"generic_grid": 1.0}
    winner = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return winner, scores
