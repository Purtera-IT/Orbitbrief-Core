from __future__ import annotations


def choose_page_escalation_policy(
    *,
    sheet_family_hint: str,
    locality_confidence: float,
    table_family_confidence: float,
    column_ambiguity: float,
    titleblock_confidence: float,
) -> dict[str, object]:
    """Return bounded escalation policy for ambiguous pages."""
    reasons: list[str] = []
    score = 0.0

    if locality_confidence < 0.75:
        score += 1.0
        reasons.append("low_locality_confidence")
    if table_family_confidence < 0.75:
        score += 1.0
        reasons.append("low_table_family_confidence")
    if column_ambiguity > 0.35:
        score += 1.0
        reasons.append("column_ambiguity")
    if titleblock_confidence < 0.7:
        score += 0.5
        reasons.append("low_titleblock_confidence")
    if sheet_family_hint in {"notes_spec", "legend_symbol", "drawing_index"}:
        score += 0.25

    if score >= 2.5:
        return {"policy": "native_plus_docling_plus_pp_structure", "reasons": reasons, "score": score}
    if score >= 1.5:
        return {"policy": "native_plus_pp_structure", "reasons": reasons, "score": score}
    if score >= 0.75:
        return {"policy": "native_plus_docling", "reasons": reasons, "score": score}
    return {"policy": "native_only", "reasons": reasons, "score": score}
