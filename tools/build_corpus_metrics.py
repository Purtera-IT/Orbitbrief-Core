"""Build corpus_metrics.yaml from a directory of compiled OrbitBrief
case artifacts (envelopes + pack_prior + site_reality).

Produces the exact summary the post-repair review asked for:
atom counts (total + by_type + by_atom_type), replay results,
site_reality outcomes, and routing distribution.

Usage::

    python tools/build_corpus_metrics.py \\
        --orbit-results /tmp/orbitbrief_core_results \\
        --out /tmp/orbitbrief_core_results/_corpus_metrics.yaml
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


def _read_json(p: Path) -> dict[str, Any] | None:
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


def _atom_review_flag_counts(envelope: dict[str, Any]) -> dict[str, int]:
    out: Counter[str] = Counter()
    for a in envelope.get("atoms") or ():
        for f in a.get("review_flags") or ():
            out[str(f)] += 1
    return dict(out)


def _atoms_by_artifact_filename(envelope: dict[str, Any]) -> dict[str, int]:
    docs = envelope.get("documents") or []
    id_to_name = {
        str(d.get("id") or d.get("artifact_id") or ""): str(d.get("filename") or "")
        for d in docs
    }
    counter: Counter[str] = Counter()
    for a in envelope.get("atoms") or ():
        aid = str(a.get("artifact_id") or "")
        counter[id_to_name.get(aid, "<unknown>")] += 1
    return dict(counter)


def _per_case(case_dir: Path) -> dict[str, Any]:
    envelope = _read_json(_candidate(case_dir, "00_envelope.json", "envelope.json")) if _candidate(case_dir, "00_envelope.json", "envelope.json") else None
    pack = _read_json(_candidate(case_dir, "10_pack_prior_state.json", "pack_prior.json")) if _candidate(case_dir, "10_pack_prior_state.json", "pack_prior.json") else None
    site = _read_json(_candidate(case_dir, "11_site_reality_state.json", "site_reality.json")) if _candidate(case_dir, "11_site_reality_state.json", "site_reality.json") else None

    out: dict[str, Any] = {"case_id": case_dir.name}

    if envelope:
        atoms = envelope.get("atoms") or []
        by_type = Counter(str(a.get("atom_type") or "") for a in atoms)
        by_artifact_type = Counter(
            str(d.get("artifact_type") or "") for d in (envelope.get("documents") or [])
        )

        # Markdown coverage — every case has a managed_services_package.md
        atoms_per_doc = _atoms_by_artifact_filename(envelope)
        md_doc_atoms = {k: v for k, v in atoms_per_doc.items() if k.lower().endswith(".md")}

        # Replay status from atom.receipts.replay_status (if present).
        replay_counts: Counter[str] = Counter()
        for a in atoms:
            for r in a.get("receipts") or ():
                replay_counts[str(r.get("replay_status") or "")] += 1

        out["envelope"] = {
            "atom_count": len(atoms),
            "by_atom_type": dict(by_type),
            "by_artifact_type": dict(by_artifact_type),
            "documents": len(envelope.get("documents") or []),
            "entities": len(envelope.get("entities") or []),
            "edges": len(envelope.get("edges") or []),
            "packets": len(envelope.get("packets") or []),
            "review_flag_counts": _atom_review_flag_counts(envelope),
            "markdown_atom_counts": md_doc_atoms,
            "replay": dict(replay_counts),
        }

    if pack:
        out["pack_prior"] = {
            "top_pack_id": pack.get("top_pack_id"),
            "top_confidence": pack.get("top_confidence"),
            "selected_pack_ids": pack.get("selected_pack_ids") or [],
            "tokens_considered": pack.get("tokens_considered"),
            "escalated": pack.get("escalated"),
        }

    if site:
        clusters = site.get("clusters") or []
        out["site_reality"] = {
            "cluster_count": len(clusters),
            "cluster_names": [c.get("canonical_name") for c in clusters][:20],
        }

    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--orbit-results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    cases = sorted(x for x in args.orbit_results.iterdir() if x.is_dir())
    per_case = [_per_case(c) for c in cases]

    # Aggregate.
    total_atoms = sum((c.get("envelope", {}) or {}).get("atom_count", 0) for c in per_case)
    by_type_total: Counter[str] = Counter()
    flag_total: Counter[str] = Counter()
    replay_total: Counter[str] = Counter()
    routing_top: Counter[str] = Counter()
    routing_pure_other = 0
    secondary_seen = 0
    md_zero_atom_docs = 0
    md_total_docs = 0
    fake_clusters: list[str] = []

    new_atom_types = {
        "risk", "asset_record", "support_entitlement", "site_roster",
        "lifecycle_status", "form_option_state",
    }
    new_atoms_total: Counter[str] = Counter()

    for c in per_case:
        env = c.get("envelope", {}) or {}
        for k, v in (env.get("by_atom_type") or {}).items():
            by_type_total[k] += v
            if k in new_atom_types:
                new_atoms_total[k] += v
        for k, v in (env.get("review_flag_counts") or {}).items():
            flag_total[k] += v
        for k, v in (env.get("replay") or {}).items():
            replay_total[k] += v
        for fname, n in (env.get("markdown_atom_counts") or {}).items():
            md_total_docs += 1
            if n == 0:
                md_zero_atom_docs += 1

        pp = c.get("pack_prior") or {}
        top = pp.get("top_pack_id")
        if top:
            routing_top[top] += 1
        sel = pp.get("selected_pack_ids") or []
        if top == "other" and not sel:
            routing_pure_other += 1
        if len(sel) > 1:
            secondary_seen += 1

        # cluster name fakeness check (mirror the regression gate)
        for n in (c.get("site_reality") or {}).get("cluster_names") or []:
            low = (n or "").lower()
            for term in ("belden", "cat6", "genetec", "axis camera", "servicenow", "synergis", "sentinel"):
                if term in low:
                    fake_clusters.append(f"{c['case_id']}::{n}")
                    break

    summary = {
        "corpus_metrics": {
            "cases": len(per_case),
            "atoms": {
                "total": total_atoms,
                "by_type": dict(by_type_total),
                "new_atom_types_emitted": dict(new_atoms_total),
            },
            "markdown_artifacts": {
                "total_md_docs": md_total_docs,
                "md_docs_with_zero_atoms": md_zero_atom_docs,
            },
            "review_flags": dict(flag_total),
            "replay": dict(replay_total),
            "routing": {
                "top_pack_distribution": dict(routing_top),
                "cases_pure_other": routing_pure_other,
                "cases_with_secondary_pack": secondary_seen,
            },
            "site_reality": {
                "fake_clusters_detected": fake_clusters,
            },
        },
        "per_case": per_case,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print(f"wrote corpus metrics → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
