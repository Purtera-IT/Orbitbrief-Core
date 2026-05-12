from __future__ import annotations

from typing import Any, Dict, Iterable, List


def close_locality_scope_if_strong(
    scoped_note: Dict[str, Any],
    *,
    same_detail_region: bool = False,
    same_subregion: bool = False,
    same_pseudo_page: bool = False,
    same_column: bool = False,
    detail_cue_present: bool = False,
) -> Dict[str, Any]:
    """
    Deterministic closure: only upgrades unresolved/mixed local scope when locality evidence is strong.
    """
    out = dict(scoped_note)
    current_scope = out.get("scope_level", out.get("scope_class", "unresolved"))
    if current_scope not in {"unresolved", "mixed", "candidate_requires_review"}:
        return out

    strength = 0
    reasons = []
    if same_detail_region:
        strength += 2
        reasons.append("same_detail_region")
    if same_subregion:
        strength += 2
        reasons.append("same_subregion")
    if same_pseudo_page:
        strength += 2
        reasons.append("same_pseudo_page")
    if same_column:
        strength += 1
        reasons.append("same_column")
    if detail_cue_present:
        strength += 1
        reasons.append("detail_cue_present")

    if strength >= 3:
        out["scope_level"] = "detail_local" if (same_detail_region or same_subregion or same_pseudo_page) else "column_local"
        out["scope_confidence"] = max(float(out.get("scope_confidence", 0.0)), 0.82)
        md = dict(out.get("metadata", {}) or {})
        md["locality_scope_closure"] = True
        md["locality_scope_closure_reasons"] = reasons
        out["metadata"] = md
    return out
