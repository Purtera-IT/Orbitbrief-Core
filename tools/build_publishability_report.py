"""Per-case publishability score (PR 20) + corpus-wide insanity gate.

For every case under ``--orbit-results``, computes a green / yellow /
red publishability rating with explicit hard_failures + warnings +
coverage numbers, then aggregates into a corpus-wide insanity_gate
result.

Usage::

    python tools/build_publishability_report.py \\
        --orbit-results /tmp/orbitbrief_core_results \\
        --out /tmp/orbitbrief_core_results/_publishability_report.yaml
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


_PUBLISHABLE_VERIFIED = {
    "verified",
    "verified_exact",
    "verified_row",
    "verified_fuzzy",
    "partial",
}
_DO_NOT_PUBLISH_FLAGS = {
    "visual_evidence_not_fully_extracted",
    "do_not_certify_as_exclusion",
    "unchecked_checkbox_ambiguous",
}
import sys as _sys
from pathlib import Path as _Path

# Make in-tree src importable from a checkout so the SOW completeness
# validator is reachable without installing the package.
_REPO_ROOT = _Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in _sys.path:
    _sys.path.insert(0, str(_SRC))

from orbitbrief_core.validator.sow_completeness import (  # noqa: E402
    SowCompletenessFinding,
    evaluate_sow_completeness,
)


_BANNED_SITE_TERMS = [
    "belden", "cat6", "cat6a", "cat 6", "cat 6a",
    "cisa", "vulnerability", "playbook",
    "servicenow", "service now", "pagerduty", "logicmonitor",
    "genetec", "axis camera", "hanwha", "milestone", "lenel",
    "apc ", "ups battery",
    "sku", "license", "contract", "sla", "sentinel",
    "synergis", "streamvault", "security center",
]


def _load_json(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _candidate(case_dir: Path, *names: str) -> Path | None:
    for n in names:
        p = case_dir / n
        if p.is_file():
            return p
    return None


def _is_publishable_atom(atom: dict[str, Any]) -> bool:
    flags = atom.get("review_flags") or ()
    if any(f in _DO_NOT_PUBLISH_FLAGS for f in flags):
        return False
    v = atom.get("verified")
    if v is None:
        return True
    return str(v) in _PUBLISHABLE_VERIFIED


def _publishability_for_case(case_dir: Path) -> dict[str, Any]:
    envelope = _load_json(_candidate(case_dir, "00_envelope.json", "envelope.json"))
    pack = _load_json(_candidate(case_dir, "10_pack_prior_state.json", "pack_prior.json"))
    site = _load_json(_candidate(case_dir, "11_site_reality_state.json", "site_reality.json"))

    hard_failures: dict[str, int] = {}
    warnings: dict[str, int] = {}

    atoms = (envelope or {}).get("atoms") or []
    pub_atoms = [a for a in atoms if _is_publishable_atom(a)]

    by_authority: Counter[str] = Counter()
    by_authority_pub: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_type_pub: Counter[str] = Counter()
    for a in atoms:
        ac = str(a.get("authority_class") or "")
        at = str(a.get("atom_type") or "")
        by_authority[ac] += 1
        by_type[at] += 1
        if _is_publishable_atom(a):
            by_authority_pub[ac] += 1
            by_type_pub[at] += 1

    high_auth_total = sum(
        by_authority.get(k, 0)
        for k in ("customer_current_authored", "approved_site_roster", "vendor_quote")
    )
    high_auth_pub = sum(
        by_authority_pub.get(k, 0)
        for k in ("customer_current_authored", "approved_site_roster", "vendor_quote")
    )
    high_auth_survival = (high_auth_pub / high_auth_total) if high_auth_total else 1.0

    exclusions = by_type.get("exclusion", 0)
    exclusions_pub = by_type_pub.get("exclusion", 0)
    excl_survival = (exclusions_pub / exclusions) if exclusions else 1.0

    quantities = by_type.get("quantity", 0)
    quantities_pub = by_type_pub.get("quantity", 0)
    qty_survival = (quantities_pub / quantities) if quantities else 1.0

    # ── routing checks ──
    sow_findings: list[SowCompletenessFinding] = []
    sow_status: str = "green"
    sow_active_domains: list[str] = []
    if pack:
        top = pack.get("top_pack_id")
        top_conf = float(pack.get("top_confidence") or 0.0)
        selected = list(pack.get("selected_pack_ids") or [])
        if top == "other":
            hard_failures["top_pack_other"] = 1
        if top == "other" and not selected:
            hard_failures["pure_other_routing"] = 1
        if abs(top_conf - 1.0) < 1e-6:
            hard_failures["top_confidence_exactly_one"] = 1

        # SOW completeness validator (29 domains × 138 checks).
        # Replaces the original PR7 narrow security-camera-only
        # validator. Returns a SowCompletenessResult; per-severity
        # totals roll into hard_failures (blocker) and warnings.
        site_clusters = (site or {}).get("clusters") or []
        sow_result = evaluate_sow_completeness(
            selected_pack_ids=selected or ([top] if top else []),
            atoms=(envelope or {}).get("atoms") or [],
            packets=(envelope or {}).get("packets") or [],
            site_clusters=site_clusters,
        )
        sow_findings = list(sow_result.findings)
        sow_status = sow_result.status
        sow_active_domains = list(sow_result.active_domain_ids)
        if sow_result.blocker_count:
            hard_failures["sow_completeness_blockers"] = sow_result.blocker_count
        if sow_result.warning_count:
            warnings["sow_completeness_warnings"] = sow_result.warning_count
        if sow_result.info_count:
            warnings["sow_completeness_info"] = sow_result.info_count

    # ── site checks ──
    if site:
        for cluster in site.get("clusters") or []:
            name = (cluster.get("canonical_name") or "").lower()
            if any(t in name for t in _BANNED_SITE_TERMS):
                hard_failures["fake_site_clusters"] = (
                    hard_failures.get("fake_site_clusters", 0) + 1
                )
            kind = cluster.get("kind") or "unknown"
            # Anything other than the publishable kinds is a warning.
            if kind not in {"physical_site", "building", "address", "room_or_closet"}:
                warnings["non_physical_site_clusters"] = (
                    warnings.get("non_physical_site_clusters", 0) + 1
                )

    # ── replay checks ──
    failed_atoms = sum(1 for a in atoms if a.get("verified") == "failed")
    if failed_atoms:
        warnings["failed_replay_atoms"] = failed_atoms

    # ── decide status ──
    status = "green"
    if hard_failures:
        status = "red"
    elif warnings:
        status = "yellow"

    return {
        "case_id": case_dir.name,
        "status": status,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "sow_completeness": {
            "status": sow_status,
            "active_domain_ids": sow_active_domains,
            "summary": {
                "total_findings": len(sow_findings),
                "blocker": sum(1 for f in sow_findings if f.severity == "blocker"),
                "warning": sum(1 for f in sow_findings if f.severity == "warning"),
                "info": sum(1 for f in sow_findings if f.severity == "info"),
            },
            "findings": [f.to_dict() for f in sow_findings],
        },
        "coverage": {
            "high_authority_atoms_total": high_auth_total,
            "high_authority_atoms_publishable": high_auth_pub,
            "high_authority_atoms_survived_pct": round(100 * high_auth_survival, 1),
            "exclusions_total": exclusions,
            "exclusions_publishable": exclusions_pub,
            "exclusions_survived_pct": round(100 * excl_survival, 1),
            "quantities_total": quantities,
            "quantities_publishable": quantities_pub,
            "quantities_survived_pct": round(100 * qty_survival, 1),
            "atoms_total": len(atoms),
            "atoms_publishable": len(pub_atoms),
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--orbit-results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    cases = sorted(x for x in args.orbit_results.iterdir() if x.is_dir())
    per_case = [_publishability_for_case(c) for c in cases]

    by_status = Counter(c["status"] for c in per_case)
    aggregate_failures: Counter[str] = Counter()
    aggregate_warnings: Counter[str] = Counter()
    for c in per_case:
        for k, v in c["hard_failures"].items():
            aggregate_failures[k] += v
        for k, v in c["warnings"].items():
            aggregate_warnings[k] += v

    insanity = {
        "insanity_gate": {
            "cases": len(per_case),
            "by_status": dict(by_status),
            "aggregate_hard_failures": dict(aggregate_failures),
            "aggregate_warnings": dict(aggregate_warnings),
            "verdict": (
                "INSANE"
                if (by_status.get("red", 0) == 0 and by_status.get("yellow", 0) == 0)
                else (
                    "STRONG"
                    if by_status.get("red", 0) == 0
                    else "NOT_YET_INSANE"
                )
            ),
        },
        "per_case": per_case,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(insanity, sort_keys=False), encoding="utf-8")
    print(f"wrote publishability + insanity gate → {args.out}")
    return 0 if by_status.get("red", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
