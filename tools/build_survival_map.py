"""Per-atom survival ledger: raw → atom → packet → bundle → brain → composer → final brief.

For every atom in the envelope of a case, walk the downstream
artifacts to record whether it survived each stage. Emits one row
per atom (or per high-authority atom if --high-only) with these
fields:

    atom_id
    artifact_id, filename, locator           ← raw provenance
    atom_type, authority_class, verified     ← atom shape
    publishable                              ← passes _DO_NOT_PUBLISH gate?
    in_packets[]                             ← packet ids that cite the atom
    in_bundles[]                             ← per-pack bundles that include it
    cited_by_brains[]                        ← brain items that cite it
    cited_by_composer                        ← True/False
    composed_brief_item_ids[]                ← composer items that cite it
    final_status                             ← 'in_brief' / 'dropped_at_<stage>' / 'qa_marker'
    drop_reason                              ← short explanation

Emits both a per-case ``survival_ledger.yaml`` and a corpus-wide
``_survival_summary.yaml`` with high-authority survival rates.

For substrate-only runs (no brains / no composer), the ledger
still produces atom → packet → bundle data and marks
``cited_by_brains=[]`` so the boss can see exactly which atoms
made it to brain visibility. Brain + composer columns populate
when --orbit-results points at a directory that has them.

Usage::

    python tools/build_survival_map.py \\
        --orbit-results /tmp/orbitbrief_core_results \\
        --out /tmp/orbitbrief_core_results/_survival_summary.yaml \\
        --per-case-out  /tmp/orbitbrief_core_results
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


_HIGH_AUTHORITY = frozenset(
    {
        "customer_current_authored",
        "approved_site_roster",
        "vendor_quote",
    }
)
_DO_NOT_PUBLISH_FLAGS = frozenset(
    {
        "visual_evidence_not_fully_extracted",
        "do_not_certify_as_exclusion",
        "unchecked_checkbox_ambiguous",
    }
)
_PUBLISHABLE_VERIFIED = frozenset(
    {
        "verified",
        "verified_exact",
        "verified_row",
        "verified_fuzzy",
        "partial",
    }
)


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _candidate(case_dir: Path, *names: str) -> Path | None:
    for n in names:
        p = case_dir / n
        if p.is_file():
            return p
    return None


def _is_publishable_atom(a: dict) -> bool:
    flags = a.get("review_flags") or ()
    if any(f in _DO_NOT_PUBLISH_FLAGS for f in flags):
        return False
    v = a.get("verified")
    if v is None:
        return True
    return str(v) in _PUBLISHABLE_VERIFIED


def _build_ledger_for_case(case_dir: Path) -> tuple[list[dict], dict]:
    envelope_p = _candidate(case_dir, "00_envelope.json", "envelope.json")
    if envelope_p is None:
        return [], {"reason": "no envelope"}
    envelope = _load_json(envelope_p)
    atoms = envelope.get("atoms") or []
    docs = {d["artifact_id"]: d for d in envelope.get("documents") or []}
    packets = envelope.get("packets") or []

    # atom_id → list of packet ids that cite it
    atom_to_packets: dict[str, list[str]] = {a["id"]: [] for a in atoms}
    for p in packets:
        for aid in (p.get("governing_atom_ids") or ()):
            atom_to_packets.setdefault(aid, []).append(p["id"])
        for aid in (p.get("supporting_atom_ids") or ()):
            atom_to_packets.setdefault(aid, []).append(p["id"])

    # atom_id → list of (pack_id, bundle_packet_id) it appears in
    bundles_dir = case_dir / "20_retrieval_bundles"
    atom_to_bundles: dict[str, list[str]] = {}
    if bundles_dir.is_dir():
        for bf in sorted(bundles_dir.glob("*.json")):
            pack_id = bf.stem
            try:
                bundle = _load_json(bf)
            except Exception:
                continue
            for snippets in (bundle.get("packets_by_family") or {}).values():
                for snip in snippets:
                    for aid in (snip.get("governing_atom_ids") or ()):
                        atom_to_bundles.setdefault(aid, []).append(pack_id)
                    for aid in (snip.get("supporting_atom_ids") or ()):
                        atom_to_bundles.setdefault(aid, []).append(pack_id)
    # Dedup the bundle entries.
    for k in list(atom_to_bundles):
        atom_to_bundles[k] = sorted(set(atom_to_bundles[k]))

    # Brain items: walk 40_brain_outputs/<pack>.json if present.
    brains_dir = case_dir / "40_brain_outputs"
    atom_to_brain_items: dict[str, list[str]] = {}
    if brains_dir.is_dir():
        for bf in sorted(brains_dir.glob("*.json")):
            pack_id = bf.stem
            try:
                state = _load_json(bf)
            except Exception:
                continue
            # Walk every list-of-items in the state and collect any
            # supporting_atom_ids per item.
            for sec_name, sec_val in (state or {}).items():
                if not isinstance(sec_val, list):
                    continue
                for item in sec_val:
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id") or item.get("item_id") or ""
                    for aid in (item.get("supporting_atom_ids") or ()):
                        atom_to_brain_items.setdefault(aid, []).append(
                            f"{pack_id}/{sec_name}/{item_id}"
                        )

    # Composer items: 80_composed_brief.json if present.
    composer_p = _candidate(
        case_dir, "80_composed_brief.json", "composed_brief.json"
    )
    atom_to_composer_items: dict[str, list[str]] = {}
    if composer_p is not None:
        try:
            cb = _load_json(composer_p)
        except Exception:
            cb = None
        if cb:
            for grp in (cb.get("domain_groups") or []):
                pack_id = grp.get("pack_id") or grp.get("display_name") or ""
                for sec in (grp.get("sections") or []):
                    sec_id = sec.get("section_id") or sec.get("section") or ""
                    for it in (sec.get("items") or []):
                        item_id = it.get("item_id") or ""
                        for aid in (it.get("supporting_atom_ids") or ()):
                            atom_to_composer_items.setdefault(aid, []).append(
                                f"{pack_id}/{sec_id}/{item_id}"
                            )

    # Per-atom rows.
    rows: list[dict] = []
    for a in atoms:
        aid = a["id"]
        doc = docs.get(a.get("artifact_id") or "", {})
        in_packets = sorted(set(atom_to_packets.get(aid, [])))
        in_bundles = atom_to_bundles.get(aid, [])
        in_brains = sorted(set(atom_to_brain_items.get(aid, [])))
        in_composer = sorted(set(atom_to_composer_items.get(aid, [])))
        publishable = _is_publishable_atom(a)

        # Decide final_status + drop_reason.
        if not publishable:
            final_status = "qa_marker_not_publishable"
            drop_reason = (
                "review_flags include a do-not-publish marker"
                if any(
                    f in _DO_NOT_PUBLISH_FLAGS
                    for f in (a.get("review_flags") or ())
                )
                else f"verified={a.get('verified')!r} (not publishable)"
            )
        elif in_composer:
            final_status = "in_brief"
            drop_reason = ""
        elif in_brains:
            final_status = "dropped_at_composer"
            drop_reason = "brain emitted item but composer dropped it"
        elif in_bundles:
            final_status = "dropped_at_brain"
            drop_reason = "in retrieval bundle but no brain item cited it"
        elif in_packets:
            final_status = "dropped_at_bundle"
            drop_reason = "in packet but no active pack's bundle included it"
        else:
            final_status = "dropped_at_packetizer"
            drop_reason = "atom did not anchor any packet"

        rows.append(
            {
                "atom_id": aid,
                "artifact_id": a.get("artifact_id"),
                "filename": doc.get("filename"),
                "locator": a.get("locator"),
                "atom_type": a.get("atom_type"),
                "authority_class": a.get("authority_class"),
                "verified": a.get("verified"),
                "publishable": publishable,
                "in_packets": in_packets,
                "in_bundles": in_bundles,
                "cited_by_brains": in_brains,
                "cited_by_composer": bool(in_composer),
                "composed_brief_item_ids": in_composer,
                "final_status": final_status,
                "drop_reason": drop_reason,
            }
        )

    summary = _summary_for_case(case_dir.name, rows)
    return rows, summary


def _summary_for_case(case_id: str, rows: list[dict]) -> dict:
    by_status = Counter(r["final_status"] for r in rows)
    high_auth = [r for r in rows if r["authority_class"] in _HIGH_AUTHORITY]
    high_pub = [r for r in high_auth if r["publishable"]]
    high_in_packet = [r for r in high_auth if r["in_packets"]]
    high_in_bundle = [r for r in high_auth if r["in_bundles"]]
    high_in_brain = [r for r in high_auth if r["cited_by_brains"]]
    high_in_brief = [r for r in high_auth if r["cited_by_composer"]]
    return {
        "case_id": case_id,
        "atoms_total": len(rows),
        "by_final_status": dict(by_status),
        "high_authority": {
            "total": len(high_auth),
            "publishable": len(high_pub),
            "in_packets": len(high_in_packet),
            "in_bundles": len(high_in_bundle),
            "cited_by_brains": len(high_in_brain),
            "in_brief": len(high_in_brief),
            "in_brief_pct": round(
                100 * len(high_in_brief) / max(len(high_auth), 1), 1
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--orbit-results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True,
                   help="Path to corpus-wide summary YAML")
    p.add_argument("--per-case-out", type=Path, default=None,
                   help="Optional dir; writes survival_ledger.yaml per case")
    args = p.parse_args(argv)

    cases = sorted(x for x in args.orbit_results.iterdir() if x.is_dir())
    summaries: list[dict] = []
    for case in cases:
        rows, summary = _build_ledger_for_case(case)
        summaries.append(summary)
        if args.per_case_out is not None:
            out_dir = args.per_case_out / case.name
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "survival_ledger.yaml").write_text(
                yaml.safe_dump({"case_id": case.name, "rows": rows}, sort_keys=False),
                encoding="utf-8",
            )

    corpus = {
        "survival_summary": {
            "cases": len(summaries),
            "atoms_total": sum(s["atoms_total"] for s in summaries),
            "high_authority_total": sum(
                s["high_authority"]["total"] for s in summaries
            ),
            "high_authority_in_brief": sum(
                s["high_authority"]["in_brief"] for s in summaries
            ),
            "high_authority_in_brief_pct": round(
                100 * sum(s["high_authority"]["in_brief"] for s in summaries)
                / max(sum(s["high_authority"]["total"] for s in summaries), 1),
                1,
            ),
        },
        "per_case": summaries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8")
    print(f"wrote survival summary → {args.out}")
    if args.per_case_out is not None:
        print(f"wrote per-case ledgers → {args.per_case_out}/<case_id>/survival_ledger.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
