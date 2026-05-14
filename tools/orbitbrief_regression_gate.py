"""Regression gate for the orbitbrief corpus.

Two modes:

1. **Smoke mode** (no ``--contract``): walks ``--orbit-results`` and
   fails on the universal failure modes — fake site clusters and
   pure-``other`` routing.

2. **Contract mode** (``--contract path/to/contract.yaml``): also
   evaluates per-case assertions (routing, atom counts, atom types,
   forbidden site terms, required artifact emissions). The contract
   is the runtime expression of ``corpus_findings.yaml`` — every
   resolved finding should map to a contract assertion that fails
   if the failure ever returns.

Usage::

    python tools/orbitbrief_regression_gate.py \\
        --orbit-results /tmp/orbitbrief_core_results

    python tools/orbitbrief_regression_gate.py \\
        --orbit-results /tmp/orbitbrief_core_results \\
        --contract tools/orbitbrief_corpus_contract.yaml
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_BANNED_FAKE_SITE_TERMS = [
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


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _candidate_files(case_dir: Path, *names: str) -> Path | None:
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


def _load_envelope(case_dir: Path) -> dict[str, Any] | None:
    """Best-effort: find an orbitbrief envelope.json under a case dir.

    Looks at common emission paths the orchestrator writes to."""
    for cand in (
        "envelope.json",
        "input_envelope.json",
        "orbitbrief_input.json",
    ):
        p = _candidate_files(case_dir, cand)
        if p is not None:
            try:
                return _load_json(p)
            except Exception:
                continue
    return None


# ──────────────────────────────────────────────────────────────────────
# Universal checks (smoke mode + always-on in contract mode)
# ──────────────────────────────────────────────────────────────────────


def _check_universal(
    case_dir: Path,
    *,
    banned_terms: list[str],
    forbid_pure_other: bool,
) -> list[str]:
    failures: list[str] = []

    site_json = _candidate_files(case_dir, "site_reality.json")
    if site_json is not None:
        try:
            payload = _load_json(site_json)
        except Exception as exc:
            failures.append(f"{case_dir.name}: site_reality.json unreadable: {exc}")
        else:
            for cluster in payload.get("clusters", []) or []:
                name = str(cluster.get("canonical_name") or "").lower()
                hit = next((t for t in banned_terms if t in name), None)
                if hit:
                    failures.append(
                        f"{case_dir.name}: fake site cluster {name!r} "
                        f"(banned term: {hit!r})"
                    )

    pack_json = _candidate_files(case_dir, "pack_prior.json")
    if pack_json is not None and forbid_pure_other:
        try:
            payload = _load_json(pack_json)
        except Exception as exc:
            failures.append(f"{case_dir.name}: pack_prior.json unreadable: {exc}")
        else:
            top = payload.get("top_pack_id")
            selected = payload.get("selected_pack_ids") or []
            if top == "other" and not selected:
                failures.append(
                    f"{case_dir.name}: routed only to 'other' "
                    "(no selected_pack_ids)"
                )

    return failures


# ──────────────────────────────────────────────────────────────────────
# Contract checks
# ──────────────────────────────────────────────────────────────────────


def _check_routing(case_dir: Path, routing: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    pack_json = _candidate_files(case_dir, "pack_prior.json")
    if pack_json is None:
        failures.append(f"{case_dir.name}: contract requires pack_prior.json (not found)")
        return failures
    try:
        payload = _load_json(pack_json)
    except Exception as exc:
        failures.append(f"{case_dir.name}: pack_prior.json unreadable: {exc}")
        return failures

    top = payload.get("top_pack_id")
    selected = list(payload.get("selected_pack_ids") or [])

    if routing.get("forbid_pure_other") and top == "other" and not selected:
        failures.append(f"{case_dir.name}: routed only to 'other' (contract.forbid_pure_other)")

    needed_any = routing.get("selected_pack_ids_include_any") or []
    if needed_any:
        present = set(selected) | ({top} if top else set())
        if not (set(needed_any) & present):
            failures.append(
                f"{case_dir.name}: routing.selected_pack_ids_include_any={needed_any} "
                f"unmet — got top={top!r}, selected={selected!r}"
            )

    needed_all = routing.get("selected_pack_ids_include_all") or []
    if needed_all:
        present = set(selected) | ({top} if top else set())
        missing = [p for p in needed_all if p not in present]
        if missing:
            failures.append(
                f"{case_dir.name}: routing.selected_pack_ids_include_all missing {missing}"
            )

    return failures


def _check_artifacts(
    case_dir: Path,
    artifact_specs: list[dict[str, Any]],
    envelope: dict[str, Any] | None,
) -> list[str]:
    failures: list[str] = []
    if envelope is None:
        failures.append(
            f"{case_dir.name}: artifact contract requires envelope.json (not found)"
        )
        return failures

    documents = envelope.get("documents") or []
    atoms_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    doc_id_to_filename: dict[str, str] = {
        str(d.get("id") or d.get("artifact_id") or ""): str(d.get("filename") or "")
        for d in documents
    }
    for atom in envelope.get("atoms") or []:
        aid = atom.get("artifact_id") or atom.get("document_id") or ""
        atoms_by_doc[str(aid)].append(atom)

    for spec in artifact_specs:
        glob = spec.get("filename_glob") or spec.get("name_contains") or "*"
        # name_contains is a substring match for back-compat with
        # the original review's wording.
        match_doc_ids: list[str] = []
        for doc_id, fname in doc_id_to_filename.items():
            if "filename_glob" in spec:
                ok = fnmatch.fnmatch(fname.lower(), str(glob).lower())
            else:
                ok = str(glob).lower() in fname.lower()
            if ok:
                match_doc_ids.append(doc_id)

        if not match_doc_ids:
            # spec.optional defaults to false — missing artifact = failure
            if not spec.get("optional"):
                failures.append(
                    f"{case_dir.name}: artifact contract — no document matches {glob!r}"
                )
            continue

        for doc_id in match_doc_ids:
            atoms = atoms_by_doc.get(doc_id, [])
            min_atoms = int(spec.get("min_atoms", 0) or 0)
            if min_atoms and len(atoms) < min_atoms:
                fname = doc_id_to_filename.get(doc_id, doc_id)
                failures.append(
                    f"{case_dir.name}: {fname!r} has {len(atoms)} atoms < min {min_atoms}"
                )
            req_any = spec.get("required_atom_types_any") or []
            if req_any:
                present = {str(a.get("atom_type") or "") for a in atoms}
                if not (set(req_any) & present):
                    fname = doc_id_to_filename.get(doc_id, doc_id)
                    failures.append(
                        f"{case_dir.name}: {fname!r} required_atom_types_any={req_any} "
                        f"unmet — got {sorted(present)[:6]}"
                    )

    return failures


def check_orbit_results(
    root: Path, contract: dict[str, Any] | None = None
) -> list[str]:
    failures: list[str] = []
    if not root.is_dir():
        return [f"orbit-results: not a directory: {root}"]

    universal_cfg = (contract or {}).get("universal", {}) or {}
    banned = universal_cfg.get("forbidden_site_terms") or _DEFAULT_BANNED_FAKE_SITE_TERMS
    forbid_pure_other = bool(
        universal_cfg.get("routing", {}).get("forbid_pure_other", True)
    )
    universal_artifacts = universal_cfg.get("artifacts") or []
    cases_cfg = (contract or {}).get("cases", {}) or {}

    for case_dir in sorted(x for x in root.iterdir() if x.is_dir()):
        failures.extend(
            _check_universal(
                case_dir,
                banned_terms=banned,
                forbid_pure_other=forbid_pure_other,
            )
        )

        if not contract:
            continue

        envelope = _load_envelope(case_dir)
        if universal_artifacts:
            failures.extend(_check_artifacts(case_dir, universal_artifacts, envelope))

        per_case = cases_cfg.get(case_dir.name) or {}
        if per_case.get("routing"):
            failures.extend(_check_routing(case_dir, per_case["routing"]))
        if per_case.get("artifacts"):
            failures.extend(_check_artifacts(case_dir, per_case["artifacts"], envelope))

    return failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_regression_gate.py")
    p.add_argument("--orbit-results", type=Path, required=True)
    p.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="Optional path to a YAML contract with per-case assertions",
    )
    args = p.parse_args(argv)

    contract: dict[str, Any] | None = None
    if args.contract is not None:
        if not args.contract.is_file():
            print(f"contract not found: {args.contract}", file=sys.stderr)
            return 2
        contract = _load_yaml(args.contract)

    failures = check_orbit_results(args.orbit_results, contract)
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print(
            f"\norbitbrief regression gate: {len(failures)} failure(s)",
            file=sys.stderr,
        )
        return 1
    print("orbitbrief regression gate: passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
