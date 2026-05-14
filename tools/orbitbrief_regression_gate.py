"""Regression gate for the corpus-review failure patterns.

Walks an ``--orbit-results`` directory of per-case orbitbrief artifacts
and fails (returns exit code 1) on any of these known regressions:

* fake site clusters — site_reality emitted a cluster whose
  canonical_name contains a banned product / vendor / framework /
  SaaS / standard term (Belden, Cat6, CISA, ServiceNow, …).
* pure-other routing — pack_prior routed only to ``other`` with no
  selected secondary packs even though there should have been
  evidence for a real pack.

This is the cheap CI check against ``findings.yaml``-style corpus
failures. Run it after every orbitbrief corpus sweep:

    python tools/orbitbrief_regression_gate.py \\
        --orbit-results /tmp/orbitbrief_core_results
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BANNED_FAKE_SITE_TERMS = [
    "belden",
    "cat6",
    "cat6a",
    "cat 6",
    "cat 6a",
    "cisa",
    "vulnerability",
    "playbook",
    "servicenow",
    "service now",
    "pagerduty",
    "logicmonitor",
    "genetec",
    "axis camera",
    "hanwha",
    "milestone",
    "lenel",
    "apc ",
    "ups battery",
    "license",
    "contract",
    "sla",
    "sku",
    "nist",
    "pci dss",
    "hipaa",
    "nfpa",
    "sentinel",
]


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_files(case_dir: Path, *names: str) -> Path | None:
    """Find the first existing file for any of ``names`` directly under
    ``case_dir`` or any one-level subdirectory (handles per-stage
    artifacts dirs the orchestrator may write under
    ``<case>/world_model/`` etc.)."""
    for n in names:
        p = case_dir / n
        if p.is_file():
            return p
    for sub in case_dir.iterdir():
        if not sub.is_dir():
            continue
        for n in names:
            p = sub / n
            if p.is_file():
                return p
    return None


def check_orbit_results(root: Path) -> list[str]:
    failures: list[str] = []
    if not root.is_dir():
        return [f"orbit-results: not a directory: {root}"]

    for case_dir in sorted(x for x in root.iterdir() if x.is_dir()):
        # ── site_reality ──
        site_json = _candidate_files(case_dir, "site_reality.json")
        if site_json is not None:
            try:
                payload = _load_json(site_json)
            except Exception as exc:
                failures.append(f"{case_dir.name}: site_reality.json unreadable: {exc}")
            else:
                for cluster in payload.get("clusters", []) or []:
                    name = str(cluster.get("canonical_name") or "").lower()
                    if any(term in name for term in BANNED_FAKE_SITE_TERMS):
                        failures.append(
                            f"{case_dir.name}: fake site cluster: {name!r}"
                        )

        # ── pack_prior ──
        pack_json = _candidate_files(case_dir, "pack_prior.json")
        if pack_json is not None:
            try:
                payload = _load_json(pack_json)
            except Exception as exc:
                failures.append(f"{case_dir.name}: pack_prior.json unreadable: {exc}")
            else:
                top = payload.get("top_pack_id")
                selected = payload.get("selected_pack_ids") or []
                if top == "other" and not selected:
                    failures.append(f"{case_dir.name}: routed only to other")

    return failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_regression_gate.py")
    p.add_argument(
        "--orbit-results",
        type=Path,
        required=True,
        help="Directory containing per-case orbitbrief artifacts",
    )
    args = p.parse_args(argv)

    failures = check_orbit_results(args.orbit_results)
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print(f"\norbitbrief regression gate: {len(failures)} failure(s)", file=sys.stderr)
        return 1
    print("orbitbrief regression gate: passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
