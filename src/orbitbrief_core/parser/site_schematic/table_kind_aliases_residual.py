from __future__ import annotations


RESIDUAL_HOLDOUT_TABLE_ALIASES: dict[str, list[list[str]]] = {
    "drawing_index": [
        ["sheet number", "sheet title", "sheet count"],
        ["drawing index", "sheet title"],
    ],
    "symbol_legend": [
        ["communications legend"],
        ["security legend"],
        ["technology legend"],
        ["symbol legend"],
    ],
    "schedule": [
        ["schedule", "qty"],
        ["specifications list"],
        ["component specifications"],
    ],
    "component_spec": [
        ["description", "manufacturer", "part number", "comments"],
        ["manufacturer", "part number", "comments"],
    ],
    "responsibility_matrix": [
        ["matrix"],
        ["responsibility matrix"],
    ],
    "outlet_definition": [
        ["outlet type", "description"],
        ["telecomm outlet", "description"],
        ["voice/data", "outlet"],
    ],
    "abbreviation_matrix": [
        ["abbreviations"],
        ["abbr"],
    ],
}


def score_residual_holdout_table_aliases(header_text: str, row_texts: list[str] | tuple[str, ...]) -> dict[str, float]:
    header_text = (header_text or "").lower()
    joined = header_text + " | " + " | ".join((row or "").lower() for row in row_texts)
    scores: dict[str, float] = {}
    for kind, signatures in RESIDUAL_HOLDOUT_TABLE_ALIASES.items():
        score = 0.0
        for sig in signatures:
            if all(tok in joined for tok in sig):
                score += 2.0
            elif any(tok in joined for tok in sig):
                score += 0.6
        if score:
            scores[kind] = score
    return scores
