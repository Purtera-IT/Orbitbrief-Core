"""Run the SOW completeness validator over one case or a corpus.

Examples:

    python tools/check_sow_completeness.py \
      --case-dir /tmp/orbitbrief_core_results/STRESS_MULTI_CAM

    python tools/check_sow_completeness.py \
      --orbit-results /tmp/orbitbrief_core_results \
      --out /tmp/orbitbrief_core_results/_sow_completeness.yaml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from orbitbrief_core.validator.sow_completeness import evaluate_from_case_payloads


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _candidate(case_dir: Path, *names: str) -> Path | None:
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


def _evaluate_case(case_dir: Path) -> dict[str, Any]:
    envelope = _load_json(_candidate(case_dir, "00_envelope.json", "envelope.json") or Path("/missing")) or {}
    pack = _load_json(_candidate(case_dir, "10_pack_prior_state.json", "pack_prior.json") or Path("/missing")) or {}
    site = _load_json(_candidate(case_dir, "11_site_reality_state.json", "site_reality.json") or Path("/missing")) or {}
    result = evaluate_from_case_payloads(envelope=envelope, pack_prior=pack, site_reality=site)
    payload = result.to_dict()
    payload["case_id"] = case_dir.name
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case-dir", type=Path)
    group.add_argument("--orbit-results", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fail-on-red", action="store_true")
    args = parser.parse_args(argv)

    if args.case_dir:
        cases = [args.case_dir]
    else:
        cases = sorted(x for x in args.orbit_results.iterdir() if x.is_dir())

    per_case = [_evaluate_case(c) for c in cases]
    aggregate = {
        "cases": len(per_case),
        "green": sum(1 for c in per_case if c["status"] == "green"),
        "yellow": sum(1 for c in per_case if c["status"] == "yellow"),
        "red": sum(1 for c in per_case if c["status"] == "red"),
        "total_findings": sum(c["summary"]["total_findings"] for c in per_case),
        "blocker": sum(c["summary"]["blocker"] for c in per_case),
        "warning": sum(c["summary"]["warning"] for c in per_case),
        "info": sum(c["summary"]["info"] for c in per_case),
    }
    payload = {"summary": aggregate, "per_case": per_case}

    text = yaml.safe_dump(payload, sort_keys=False, width=120)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote SOW completeness report -> {args.out}")
    else:
        print(text)

    return 1 if args.fail_on_red and aggregate["red"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
