"""Shared helpers for teacher/judge heads: atom tagging + citation grounding.

The teacher must cite atom tags (A1..AN); we validate every cited tag exists, so
fabrication is structurally impossible (a claim that cites nothing real is dropped).
"""
from __future__ import annotations

import re
from typing import Any

# Tier-1: a DEAL-LEVEL total (the whole deal/contract/program), not a sub-component.
_DEAL_LEVEL = re.compile(
    r"total\s+(deal|contract|project|program)|(deal|contract|program|estimated|grand)\s+total|"
    r"total\s+(deal\s+)?(revenue|value|price|amount|contract\s+value)", re.I)
_SUBCOMPONENT = re.compile(
    r"\b(labor|labour|pmo|material|travel|expense|hardware|software|licen[sc]e|per\s+day|"
    r"per\s+hour|hourly|daily|monthly|weekly|unit|each|tax|shipping|freight|rate|cost)\b", re.I)
# Tier-2 fallback: any 'total ... revenue' total (incl. labor-only deals).
_REVENUE_TOTAL = re.compile(r"total\s+[a-z ]*\brevenue\b", re.I)
_NUM = re.compile(r"([\d][\d,]{2,}(?:\.\d+)?)")  # >=3 digits; skips small index cols like col_2


def _largest_amount(text: str) -> float | None:
    """First plausible deal amount in the atom — the value usually follows the label,
    so take the FIRST number in [100, 1e9]. (Taking the max wrongly grabs margin
    decimal digits, e.g. 0.2784090909 -> 2784090909.)"""
    for m in _NUM.findall(text or ""):
        try:
            v = float(m.replace(",", ""))
        except ValueError:
            continue
        if 100 <= v <= 1_000_000_000:
            return v
    return None


def resolve_deal_total(envelope: dict) -> float | None:
    """Authoritative deal total. NEVER ``pm_dashboard.money_summary.total`` (a naive
    sum that inflates 6-12x). Priority: deal_financials.totals.revenue > overall_total
    > a DEAL-LEVEL total atom (tier 1) > a single 'total ... revenue' atom (tier 2,
    labor-only deals) > None. Never sums line items."""
    def _num(v):
        # "48500", "48,500.00", "$48,500" are the same number as 48500.0 --
        # a producer's JSON dressing must not decide whether the deal total
        # exists. Booleans are not amounts.
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", "").replace("$", "").strip())
            except ValueError:
                return None
        return None

    df = envelope.get("deal_financials") or {}
    rev = _num((df.get("totals") or {}).get("revenue"))
    if rev is not None and rev > 0:
        return rev
    ot = _num(df.get("overall_total"))
    if ot is not None and ot > 0:
        return ot
    tier1, tier2 = [], []
    for a in (envelope.get("atoms") or []):
        if a.get("atom_type") not in ("commercial_total", "service_line", "deal_metadata",
                                      "vendor_line_item", "pricing_assumption"):
            continue
        t = a.get("text") or ""
        amt = _largest_amount(t)
        if amt is None:
            continue
        if _DEAL_LEVEL.search(t) and not _SUBCOMPONENT.search(t):
            tier1.append(amt)
        elif _REVENUE_TOTAL.search(t):
            tier2.append(amt)
    if tier1:
        return max(tier1)
    if tier2:
        return max(tier2)
    return None


def count_blockers(envelope: dict) -> int:
    """Real blocker count from the parser dashboard — never 0-by-default, never a
    gap-count guess. ``pm_dashboard.blockers`` is the authoritative list."""
    pm = envelope.get("pm_dashboard") or {}
    return len(pm.get("blockers") or [])


def tag_atoms(envelope: dict, keep_types: set[str] | None, limit: int = 60,
              with_doc: bool = False) -> tuple[str, dict[str, dict]]:
    """Return (rendered_context, tagmap). Atoms are filtered to ``keep_types``
    (all types if None) and tagged A1..AN. ``with_doc`` prefixes the source doc."""
    docs = {d.get("artifact_id"): (d.get("filename") or "")[:22]
            for d in (envelope.get("documents") or [])}
    atoms = [a for a in (envelope.get("atoms") or [])
             if (keep_types is None or a.get("atom_type") in keep_types)
             and (a.get("text") or "").strip()][:limit]
    tagmap: dict[str, dict] = {}
    lines = []
    for i, a in enumerate(atoms, 1):
        tag = f"A{i}"
        tagmap[tag] = a
        prefix = f"({docs.get(a.get('artifact_id'), '?')}) " if with_doc else ""
        lines.append(f"  {tag}: {prefix}[{a.get('atom_type')}] {(a.get('text') or '')[:130]}")
    return "\n".join(lines), tagmap


def valid_cites(item: dict, tagmap: dict[str, dict], min_cites: int = 1) -> list[str]:
    """Keep only cited tags that exist; returns [] if fewer than ``min_cites``."""
    cited = [t for t in (item.get("atom_ids") or item.get("evidence_ids") or []) if t in tagmap]
    return cited if len(cited) >= min_cites else []
