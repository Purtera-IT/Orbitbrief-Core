"""Track A — eight envelope→handoff passthroughs.

parser-os has already computed the data; we just plumb it through.
Every transformation here is defensive: a missing envelope field
becomes an empty dict/list, never a crash.  That keeps compile_brief
robust to schema drift while we ship the v46 enrichment surface.
"""
from __future__ import annotations

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
    """58 sites with per-site readiness scores instead of the 18 names."""
    sr = _safe_dict(env.get("site_readiness"))
    sites = _safe_list(sr.get("sites"))
    out: list[dict] = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        out.append({
            "site_slug": s.get("slug") or s.get("site") or s.get("name"),
            "name": s.get("name") or s.get("display_name"),
            "readiness_score": s.get("readiness_score") or s.get("score"),
            "missing_dimensions": _safe_list(s.get("missing_dimensions")),
            "atom_count": s.get("atom_count"),
            "least_ready_reason": s.get("least_ready_reason"),
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
            "iso_date": e.get("iso") or e.get("iso_date"),
            "delta": e.get("delta") or e.get("structured_delta"),
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
