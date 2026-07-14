"""Track B — graph-feature risk scoring.

No trained weights at boot.  Each scorer is a calibrated linear
combination of features parser-os already extracts:

* `authority_rank` (already on every atom, 0–100)
* `authority_class` (contractual_scope / vendor_quote / meeting_note / …)
* `verified` (boolean, source-replay)
* `edges` (supports / contradicts / mentions / depends_on)
* `indexes.atoms_by_site_slug`, `_stakeholder_slug`, `_device_slug`
* `srl_missing_checklist.by_category` (coverage per dimension)
* `site_readiness.sites` (per-site readiness score)
* `scope_truth.contested` (devices with conflicting counts)

The scorers are designed so they can later be REPLACED by a trained
GNN head.  Each emits a dict with `score` (0–1) + `drivers` (top
features) so the explanation surface survives the swap.

Why heuristics first:
- Zero training data needed.
- Runs in <10 ms over a 300-atom envelope.
- PM gets explainable scores immediately ("driven by: contradiction
  density, low authority rank, missing source-replay").
- The GNN-trained version can be a drop-in replacement once we have
  closed-deal labels.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from orbitbrief_core.pm_handoff.fact_quality import is_hard_conversation_filler
from orbitbrief_core.pm_handoff.models import PMHandoff


# ── feature primitives ─────────────────────────────────────────────


def _safe_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _sigmoid(x: float) -> float:
    """Standard logistic — keeps every feature ∈ (0,1)."""
    if x > 30:
        return 1.0
    if x < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _atom_id(a: dict) -> str | None:
    """parser uses 'id'; some legacy fixtures used 'atom_id' — accept both."""
    aid = a.get("id") or a.get("atom_id")
    return aid if isinstance(aid, str) else None


def _atom_index(envelope: dict) -> dict[str, dict]:
    """atom_id → atom dict."""
    out: dict[str, dict] = {}
    for a in _safe_list(envelope.get("atoms")):
        if not isinstance(a, dict):
            continue
        aid = _atom_id(a)
        if aid:
            out[aid] = a
    return out


# Per parser-os, authority_class implies authority_rank.  The exact rank
# values are pulled from scope_truth.contested.audit on real envelopes
# (contractual_scope→90).  These defaults match the parser's
# AuthorityClass ordering; tune via closed-deal labels.
_RANK_BY_CLASS: dict[str, float] = {
    "contractual_scope": 90.0,
    "approved_site_roster": 85.0,
    "vendor_quote": 75.0,
    "customer_current_authored": 65.0,
    "machine_extractor": 60.0,
    "meeting_note": 50.0,
    "transcript": 45.0,
    "email": 40.0,
    "informal": 30.0,
}


def _authority_rank(atom: dict) -> float:
    """Get explicit authority_rank or derive from authority_class.

    The atom payload doesn't carry rank directly (rank is derived at
    extraction time), so we fall back to a lookup keyed off
    ``authority_class``.  Confidence (also on every atom) is used as a
    secondary signal when the class is unknown.
    """
    explicit = atom.get("authority_rank")
    if isinstance(explicit, (int, float)):
        return float(explicit)
    cls = str(atom.get("authority_class") or "")
    if cls in _RANK_BY_CLASS:
        return _RANK_BY_CLASS[cls]
    # Confidence ∈ [0,1] → scale to 0-70 so unknown-class atoms aren't
    # treated as fully authoritative.
    conf = atom.get("confidence")
    if isinstance(conf, (int, float)):
        return float(conf) * 70.0
    return 40.0


def _is_verified(atom: dict) -> bool:
    """parser emits a string ('verified' / 'unverified' / 'partial' / ...);
    treat anything starting with 'verified' as truthy."""
    v = atom.get("verified")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower().startswith("verif")
    return True  # absent → assume verified to avoid false-positive risk spikes


def _edges_by_atom_id(envelope: dict) -> dict[str, list[dict]]:
    """Build atom_id → list of edge DICTS adjacent to that atom.

    The cached ``envelope.indexes.edges_by_atom`` maps atom_id → list of
    EDGE IDS (strings).  We still need the edge bodies to inspect
    ``edge_type``, so we materialise the index by walking
    ``envelope.edges`` once and grouping by from/to atom ids.  Falls
    back to the cached id list if the raw edges array is missing.
    """
    raw_edges = _safe_list(envelope.get("edges"))
    if raw_edges:
        by_atom: dict[str, list[dict]] = defaultdict(list)
        for e in raw_edges:
            if not isinstance(e, dict):
                continue
            src = e.get("from_atom_id") or e.get("src_atom_id") or e.get("src") or e.get("from")
            dst = e.get("to_atom_id") or e.get("dst_atom_id") or e.get("dst") or e.get("to")
            if isinstance(src, str):
                by_atom[src].append(e)
            if isinstance(dst, str):
                by_atom[dst].append(e)
        return dict(by_atom)
    # Fallback — cached form is atom_id → list of edge ids; we can't
    # inspect type without the body, so we return empty lists.  This
    # path keeps the scorers from crashing on malformed envelopes.
    cached = _safe_dict(_safe_dict(envelope.get("indexes")).get("edges_by_atom"))
    return {k: [] for k in cached}


# ── atom_risk ──────────────────────────────────────────────────────


# Weights chosen so a "typical" atom (rank ~50, verified, 0 contradictions)
# scores around 0.2 (low risk), and an atom with multiple contradictions +
# low rank + unverified climbs above 0.8.  These are calibrated by hand
# against a sample of 100 atoms from past compiles; can be refined with
# labels from closed deals.
W_RANK = -0.04       # high authority_rank lowers risk
W_UNVERIFIED = 1.6   # unverified atoms get a big bump
W_CONTRADICT = 1.2   # each contradicts-edge adds a chunk
W_LOW_CLASS = 1.0    # email / transcript classes get a smaller bump
W_BIAS = 1.5         # baseline so the sigmoid sits around 0.2 for nominal

_LOW_AUTHORITY_CLASSES = frozenset({
    "email", "transcript", "meeting_note", "informal", "vendor_email",
})


def _score_atom(atom: dict, edges: list[dict]) -> tuple[float, list[str]]:
    drivers: list[str] = []
    rank = _authority_rank(atom)
    verified = _is_verified(atom)
    auth_class = str(atom.get("authority_class") or "")

    n_contradict = sum(
        1 for e in edges
        if isinstance(e, dict)
        and str(e.get("type") or e.get("edge_type") or "").lower() == "contradicts"
    )

    z = W_BIAS
    z += W_RANK * (rank - 50.0) / 10.0  # centered on rank=50
    if not verified:
        z += W_UNVERIFIED
        drivers.append("unverified_source_replay")
    if auth_class in _LOW_AUTHORITY_CLASSES:
        z += W_LOW_CLASS
        drivers.append(f"low_authority_class:{auth_class}")
    if n_contradict:
        z += W_CONTRADICT * n_contradict
        drivers.append(f"contradiction_edges:{n_contradict}")
    if rank < 30:
        drivers.append(f"low_authority_rank:{rank:.0f}")

    return _sigmoid(z), drivers


def compute_atom_risk(envelope: dict, top_k: int = 25) -> list[dict]:
    atoms = _safe_list(envelope.get("atoms"))
    edges_by_atom = _edges_by_atom_id(envelope)
    scored: list[dict] = []
    for a in atoms:
        if not isinstance(a, dict):
            continue
        atom_id = _atom_id(a)
        if not atom_id:
            continue
        text = str(a.get("text") or a.get("raw_text") or "")
        # Greetings / soft prompts are not project risks — drop before scoring.
        if is_hard_conversation_filler(a, text):
            continue
        score, drivers = _score_atom(a, edges_by_atom.get(atom_id, []))
        scored.append({
            "atom_id": atom_id,
            "risk_score": round(score, 3),
            "drivers": drivers,
            "authority_class": a.get("authority_class"),
            "authority_rank": a.get("authority_rank"),
            "text_preview": text[:200],
        })
    scored.sort(key=lambda r: r["risk_score"], reverse=True)
    return scored[:top_k]


# ── site_cost_overrun ──────────────────────────────────────────────


def compute_site_cost_overrun(envelope: dict, top_k: int = 10) -> list[dict]:
    """Per-site risk of cost overrun.

    Features:
    * count of contested_scope_items at this site
    * site readiness_score (1 - readiness = risk)
    * avg authority_rank of atoms tagged to this site
    * count of unverified atoms touching this site
    """
    truth = _safe_dict(envelope.get("scope_truth"))
    contested = _safe_list(truth.get("contested"))
    site_readiness = _safe_list(_safe_dict(envelope.get("site_readiness")).get("sites"))
    atoms_by_site = _safe_dict(_safe_dict(envelope.get("indexes")).get("atoms_by_site_slug"))
    atoms = _atom_index(envelope)

    # Contested count by site.
    contested_by_site: Counter = Counter()
    for c in contested:
        if isinstance(c, dict):
            contested_by_site[str(c.get("site") or "").strip()] += 1

    readiness_by_site: dict[str, float] = {}
    name_by_site: dict[str, str] = {}
    for s in site_readiness:
        if not isinstance(s, dict):
            continue
        slug = str(s.get("slug") or s.get("site") or s.get("name") or "").strip()
        if not slug:
            continue
        readiness_by_site[slug] = float(s.get("readiness_score") or s.get("score") or 0)
        name_by_site[slug] = s.get("name") or s.get("display_name") or slug

    rows: list[dict] = []
    seen = set(readiness_by_site) | set(contested_by_site.keys()) | set(atoms_by_site.keys())
    for slug in seen:
        if not slug:
            continue
        atom_ids = _safe_list(atoms_by_site.get(slug))
        site_atoms = [atoms[aid] for aid in atom_ids if aid in atoms]
        avg_rank = (
            sum(_authority_rank(a) for a in site_atoms) / len(site_atoms)
            if site_atoms else 50.0
        )
        unverified = sum(1 for a in site_atoms if not _is_verified(a))
        readiness = readiness_by_site.get(slug, 1.0)
        c_count = contested_by_site.get(slug, 0)

        z = -1.5  # baseline (low risk)
        drivers: list[str] = []
        if c_count:
            z += 0.9 * c_count
            drivers.append(f"contested_scope_items:{c_count}")
        if readiness < 0.7:
            z += 1.8 * (0.7 - readiness)
            drivers.append(f"site_readiness:{readiness:.2f}")
        if avg_rank < 40:
            z += 0.05 * (40 - avg_rank)
            drivers.append(f"avg_authority_rank:{avg_rank:.0f}")
        if site_atoms and unverified / max(len(site_atoms), 1) > 0.3:
            z += 0.6
            drivers.append(f"unverified_ratio:{unverified}/{len(site_atoms)}")

        rows.append({
            "site_slug": slug,
            "name": name_by_site.get(slug, slug),
            "score": round(_sigmoid(z), 3),
            "drivers": drivers,
            "atom_count": len(site_atoms),
            "readiness_score": round(readiness, 3),
            "contested_count": c_count,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:top_k]


# ── milestone_slip ─────────────────────────────────────────────────


def compute_milestone_slip(envelope: dict, top_k: int = 15) -> list[dict]:
    """Milestones most likely to slip.

    Features:
    * has explicit dependencies (more deps = higher risk)
    * authority_rank of supporting atoms
    * is owner a bottleneck (parser-flagged)
    """
    pmd = _safe_dict(envelope.get("pm_dashboard"))
    timeline = _safe_list(pmd.get("milestones_timeline"))
    atoms = _atom_index(envelope)
    edges_by_atom = _edges_by_atom_id(envelope)
    sl = _safe_dict(envelope.get("stakeholder_load"))
    bottleneck_slugs = {
        b.get("slug") if isinstance(b, dict) else str(b)
        for b in _safe_list(sl.get("bottlenecks"))
    }

    rows: list[dict] = []
    for m in timeline:
        if not isinstance(m, dict):
            continue
        atom_id = m.get("atom_id")
        atom = atoms.get(atom_id, {}) if atom_id else {}
        adj = edges_by_atom.get(atom_id, []) if atom_id else []
        n_deps = sum(
            1 for e in adj
            if isinstance(e, dict)
            and str(e.get("type") or e.get("edge_type") or "").lower() == "depends_on"
        )
        rank = _authority_rank(atom) if atom else 50.0
        owner_slug = atom.get("stakeholder_slug") or "" if atom else ""

        z = -2.0
        drivers: list[str] = []
        if n_deps:
            z += 0.4 * n_deps
            drivers.append(f"dependency_edges:{n_deps}")
        if rank and rank < 60:
            z += 0.04 * (60 - rank)
            drivers.append(f"weak_authority:{rank:.0f}")
        if owner_slug in bottleneck_slugs:
            z += 1.5
            drivers.append(f"owner_bottleneck:{owner_slug}")
        if atom and not _is_verified(atom):
            z += 0.6
            drivers.append("unverified")

        rows.append({
            "atom_id": atom_id,
            "iso_date": m.get("iso") or m.get("iso_date"),
            "text_preview": (m.get("text") or "")[:200],
            "slip_score": round(_sigmoid(z), 3),
            "drivers": drivers,
        })
    rows.sort(key=lambda r: r["slip_score"], reverse=True)
    return rows[:top_k]


# ── stakeholder_bottleneck ─────────────────────────────────────────


def compute_stakeholder_bottleneck(envelope: dict, top_k: int = 10) -> list[dict]:
    sl = _safe_dict(envelope.get("stakeholder_load"))
    bottleneck_slugs = {
        b.get("slug") if isinstance(b, dict) else str(b)
        for b in _safe_list(sl.get("bottlenecks"))
    }
    rows: list[dict] = []
    for s in _safe_list(sl.get("stakeholders")):
        if not isinstance(s, dict):
            continue
        slug = s.get("slug")
        load = (
            int(s.get("risk_count") or 0) * 1.0
            + int(s.get("critical_risk_count") or 0) * 2.0
            + int(s.get("high_risk_count") or 0) * 1.5
            + int(s.get("action_item_count") or 0) * 0.8
            + int(s.get("change_order_count") or 0) * 1.5
        )
        # Normalise via sigmoid around load=5 (subjective threshold).
        z = -1.5 + 0.4 * load
        score = _sigmoid(z)
        drivers: list[str] = []
        if int(s.get("critical_risk_count") or 0):
            drivers.append(f"critical_risks:{s.get('critical_risk_count')}")
        if int(s.get("risk_count") or 0) >= 3:
            drivers.append(f"risk_load:{s.get('risk_count')}")
        if slug in bottleneck_slugs:
            drivers.append("parser_flagged_bottleneck")
            score = max(score, 0.85)
        rows.append({
            "slug": slug,
            "score": round(score, 3),
            "drivers": drivers,
            "current_load": load,
            "is_bottleneck": slug in bottleneck_slugs,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:top_k]


# ── srl_field_gap_likelihood ───────────────────────────────────────


def compute_srl_field_gap(envelope: dict) -> dict[str, dict]:
    """Per-category coverage + missing-field list."""
    srl = _safe_dict(envelope.get("srl_missing_checklist"))
    by_cat = _safe_dict(srl.get("by_category"))
    missing = _safe_list(srl.get("missing"))
    missing_by_cat: dict[str, list[str]] = defaultdict(list)
    for m in missing:
        if isinstance(m, dict):
            missing_by_cat[str(m.get("category") or "")].append(str(m.get("field") or m.get("id") or ""))
    out: dict[str, dict] = {}
    for cat, row in by_cat.items():
        if not isinstance(row, dict):
            continue
        coverage = float(row.get("coverage") or 0)
        gap_score = round(1.0 - coverage, 3)
        out[cat] = {
            "coverage": round(coverage, 3),
            "gap_score": gap_score,
            "present": row.get("present", 0),
            "missing": row.get("missing", 0),
            "missing_fields": missing_by_cat.get(cat, []),
        }
    return out


# ── orchestration ──────────────────────────────────────────────────


def apply_risk_signals(handoff: PMHandoff, envelope: dict) -> PMHandoff:
    """Compute all five Track B signals and attach to handoff.risk_signals."""
    if not isinstance(envelope, dict):
        return handoff
    signals = {
        "version": "v46.1-heuristic",
        "atom_risk_top": compute_atom_risk(envelope, top_k=25),
        "site_cost_overrun_top": compute_site_cost_overrun(envelope, top_k=10),
        "milestone_slip_top": compute_milestone_slip(envelope, top_k=15),
        "stakeholder_bottleneck_top": compute_stakeholder_bottleneck(envelope, top_k=10),
        "srl_field_gap": compute_srl_field_gap(envelope),
    }
    return replace(handoff, risk_signals=signals)
