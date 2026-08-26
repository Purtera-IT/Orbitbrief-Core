"""Track A — eight envelope→handoff passthroughs.

parser-os has already computed the data; we just plumb it through.
Every transformation here is defensive: a missing envelope field
becomes an empty dict/list, never a crash.  That keeps compile_brief
robust to schema drift while we ship the v46 enrichment surface.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from orbitbrief_core.pm_handoff.models import PMHandoff


def _safe_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _project_vitals(env: dict) -> dict:
    pv = _safe_dict(env.get("project_vitals"))
    if not pv:
        return {}
    return {
        "score_100": pv.get("score_100"),
        "band": pv.get("band"),
        "components": _safe_list(pv.get("components")),
        "top_drivers": _safe_list(pv.get("top_drivers")),
        "top_detractors": _safe_list(pv.get("top_detractors")),
    }


def _sow_readiness_dimensions(env: dict) -> dict:
    scorecard = _safe_dict(env.get("sow_readiness_scorecard"))
    if not scorecard:
        return {}
    return {
        "readiness_score": scorecard.get("readiness_score"),
        "grade": scorecard.get("grade"),
        # Provenance for the blocker-capped grade so the PM sees WHY a deal
        # isn't "ready" (was dropped here, leaving the capped grade unexplained).
        "blocker_count": scorecard.get("blocker_count"),
        "blocked": scorecard.get("blocked"),
        "grade_capped_by_blockers": scorecard.get("grade_capped_by_blockers"),
        "dimensions": _safe_dict(scorecard.get("dimensions")),
        "description_by_dimension": _safe_dict(scorecard.get("description_by_dimension")),
    }


# A standards citation is not a quantity. Measured on a real deal 2026-08-14 the
# contested-scope surface reported:
#
#   device:rack   canonical_quantity=1992   competing=[6, 24]
#     qty 1992  contractual_scope  rank 90
#       "NUMBER: EIA-310 (Sep 1992) | TITLE: Racks, Panels and Associated Equipment"
#
# 1992 is the YEAR of the EIA-310 revision. It outranked the real claims because
# a standards document is contractual_scope (rank 90), so the false value did not
# just appear — it WON. Shipping "1992 racks" to a PM discredits every genuine
# conflict on the page.
_CITATION_RE = re.compile(
    r"(?i)\b(eia|tia|ansi|iso|iec|ieee|nfpa|astm|ul|bicsi|ashrae|nec)\b[\s-]*\d"
    r"|\brev(?:ision)?\.?\s*\d"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\b"
    r"|\bpublished\b|\bstandard\b|\bspecification\s+no"
)


def _is_citation_year(quantity: Any, text: str) -> bool:
    """True when a 'quantity' is a year lifted out of a standards citation."""
    try:
        q = int(quantity)
    except (TypeError, ValueError):
        return False
    if not (1900 <= q <= 2099):
        return False
    return bool(_CITATION_RE.search(text or ""))


def _clean_contested(entry: dict) -> dict | None:
    """Drop citation-year claims and re-derive the canonical value without them.

    Only removes claims that are BOTH a plausible year and sitting in a citation.
    A genuine quantity that happens to be 2024 in ordinary prose is untouched.
    """
    audit = _safe_list(entry.get("audit"))
    kept_audit: list[dict] = []
    dropped: set = set()
    for row in audit:
        if not isinstance(row, dict):
            continue
        claims = [
            c for c in _safe_list(row.get("claims"))
            if isinstance(c, dict)
            and not _is_citation_year(c.get("quantity"), str(c.get("text") or ""))
        ]
        if claims:
            kept_audit.append({**row, "claims": claims})
        else:
            dropped.add(row.get("quantity"))
    if not kept_audit:
        return None
    canonical = entry.get("canonical_quantity")
    if canonical in dropped:
        # Re-derive: highest authority rank wins, then the most-supported value.
        best, best_key = None, (-1, -1)
        for row in kept_audit:
            for c in row.get("claims") or []:
                key = (int(c.get("authority_rank") or 0), len(row.get("claims") or []))
                if key > best_key:
                    best_key, best = key, c.get("quantity")
        canonical = best
    competing = [
        v for v in _safe_list(entry.get("competing_values"))
        if v not in dropped and v != canonical
    ]
    if not competing:
        return None  # nothing left to contest
    return {**entry, "canonical_quantity": canonical, "competing_values": competing,
            "audit": kept_audit}


def _contested_scope_items(env: dict) -> list[dict]:
    """The five-alarm fire surface.

    Each entry is a (device, site, canonical_quantity, competing_values,
    audit) tuple where the parser found multiple documents quoting
    different quantities for the same device-at-site.  PM needs to
    resolve these BEFORE signing — they otherwise become change orders.
    """
    truth = _safe_dict(env.get("scope_truth"))
    contested = _safe_list(truth.get("contested"))
    out: list[dict] = []
    for c in contested:
        if not isinstance(c, dict):
            continue
        cleaned = _clean_contested(c)
        if cleaned is None:
            continue
        c = cleaned
        out.append({
            "device": c.get("device"),
            "site": c.get("site"),
            "canonical_quantity": c.get("canonical_quantity"),
            "competing_values": _safe_list(c.get("competing_values")),
            # audit carries (quantity, claims[]) tuples — preserve full
            # provenance so the UI can show "SOW: 3" vs "Quote: 15".
            "audit": _safe_list(c.get("audit")),
        })
    return out


def _site_readiness(env: dict) -> list[dict]:
    """Per-site readiness rows, read with the keys the envelope actually uses.

    ``build_site_readiness`` emits ``site`` / ``readiness`` / ``facility_name``
    / ``scope_atom_count`` / ``maturity`` / ``band``. This mapper used to ask
    for ``slug`` / ``readiness_score`` / ``name`` / ``atom_count`` /
    ``least_ready_reason`` — five names that do not exist on the row. Only
    ``site`` matched, so the brief rendered one slug per site and null for
    every other column: 437 rows that each said nothing. The data was in the
    envelope the whole time.

    ``missing_dimensions`` is derived rather than looked up: the envelope
    carries the per-signal counts, and a dimension is missing exactly when its
    count is zero. That is what the field name has always promised.
    """
    sr = _safe_dict(env.get("site_readiness"))
    sites = _safe_list(sr.get("sites"))
    out: list[dict] = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        missing = [
            label
            for label, present in (
                ("devices", s.get("device_count") or 0),
                ("stakeholders", s.get("stakeholder_count") or 0),
                ("constraints", s.get("constraint_count") or 0),
                ("scope", s.get("scope_atom_count") or 0),
                ("commercials", 1 if s.get("money_present") else 0),
                ("schedule", 1 if s.get("milestone_present") else 0),
            )
            if not present
        ]
        maturity = s.get("maturity")
        out.append({
            "site_slug": s.get("site") or s.get("slug") or s.get("name"),
            "name": s.get("facility_name") or s.get("name") or s.get("display_name"),
            "address": s.get("street_address") or s.get("address"),
            "readiness_score": s.get("readiness", s.get("readiness_score", s.get("score"))),
            "band": s.get("band"),
            "maturity": maturity,
            "missing_dimensions": missing,
            "atom_count": s.get("scope_atom_count", s.get("signal_count", s.get("atom_count"))),
            "least_ready_reason": (
                s.get("least_ready_reason")
                or (f"{maturity}: no {', '.join(missing)} evidence yet" if missing and maturity else None)
            ),
        })
    return out


def _milestones(env: dict) -> list[dict]:
    """All 63 dated events, not 6 phase rollups."""
    pmd = _safe_dict(env.get("pm_dashboard"))
    timeline = _safe_list(pmd.get("milestones_timeline"))
    out: list[dict] = []
    for m in timeline:
        if not isinstance(m, dict):
            continue
        out.append({
            "atom_id": m.get("atom_id"),
            "iso_date": m.get("iso"),
            "text": m.get("text"),
        })
    return out


def _stakeholder_load(env: dict) -> list[dict]:
    """Per-stakeholder load with bottleneck signal."""
    sl = _safe_dict(env.get("stakeholder_load"))
    stakeholders = _safe_list(sl.get("stakeholders"))
    out: list[dict] = []
    for s in stakeholders:
        if not isinstance(s, dict):
            continue
        out.append({
            "slug": s.get("slug"),
            "risk_count": s.get("risk_count", 0),
            "risk_severity_load": s.get("risk_severity_load", 0),
            "critical_risk_count": s.get("critical_risk_count", 0),
            "high_risk_count": s.get("high_risk_count", 0),
            "action_item_count": s.get("action_item_count", 0),
            "decision_count": s.get("decision_count", 0),
            "change_order_count": s.get("change_order_count", 0),
            "is_bottleneck": False,  # populated below
        })
    # mark bottlenecks: parser already computes them, but we re-flag
    # here for ease of access from the handoff side.
    bottleneck_slugs = {
        b.get("slug") if isinstance(b, dict) else str(b)
        for b in _safe_list(sl.get("bottlenecks"))
    }
    for row in out:
        if row["slug"] in bottleneck_slugs:
            row["is_bottleneck"] = True
    return out


def _evidence_authority(env: dict) -> dict:
    """Distribution of atoms across authority classes — confidence atlas.

    Tells the UI how much of the brief rests on SOW-grade evidence vs
    email/transcript.  A brief with 200 contractual_scope atoms is on
    much firmer ground than one resting on 200 email atoms.
    """
    summary = _safe_dict(env.get("summary"))
    by_class = _safe_dict(summary.get("by_authority_class"))
    if not by_class:
        return {}
    total = sum(int(v) for v in by_class.values() if isinstance(v, (int, float)))
    out = {
        "total_atoms": total,
        "by_class": dict(by_class),
        "by_class_pct": {
            k: round(100.0 * int(v) / total, 1)
            for k, v in by_class.items()
            if isinstance(v, (int, float)) and total > 0
        },
    }
    return out


def _change_order_timeline(env: dict) -> list[dict]:
    """Structured deltas with approval signal — richer than the existing
    change_order_triggers count.
    """
    cot = _safe_dict(env.get("change_order_timeline"))
    entries = _safe_list(cot.get("entries"))
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        out.append({
            "atom_id": e.get("atom_id"),
            # `iso` / `delta` are not emitted by build_change_order_timeline —
            # kept so the shape stays stable if it starts emitting them.
            "iso_date": e.get("iso") or e.get("iso_date"),
            "delta": e.get("delta") or e.get("structured_delta"),
            # `kind` IS on every entry and was being dropped on the floor.
            "kind": e.get("kind"),
            "approval_signal": e.get("approval_signal"),
            "text": e.get("text"),
        })
    return out


def apply_envelope_passthroughs(handoff: PMHandoff, envelope: dict) -> PMHandoff:
    """Return a new PMHandoff with the eight Track A fields populated.

    ``envelope`` is the full parser-os envelope dict (loaded from the
    ``envelope.json`` blob).  Missing fields gracefully degrade to
    empty containers — never raises.
    """
    if not isinstance(envelope, dict):
        return handoff
    return replace(
        handoff,
        project_vitals=_project_vitals(envelope),
        sow_readiness_dimensions=_sow_readiness_dimensions(envelope),
        contested_scope_items=_contested_scope_items(envelope),
        site_readiness=_site_readiness(envelope),
        milestones=_milestones(envelope),
        stakeholder_load=_stakeholder_load(envelope),
        evidence_authority=_evidence_authority(envelope),
        change_order_timeline=_change_order_timeline(envelope),
    )
