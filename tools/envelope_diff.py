#!/usr/bin/env python3
"""C6: Envelope diff tool for deal updates.

Compares two ``orbitbrief.input.v2`` envelopes (e.g. last week's
brief vs this week's brief on the same deal) and prints what
changed at the PM-actionable level:

* New / removed source files
* New / removed sites
* New / removed stakeholders
* Money values added or removed
* Risk register additions / removals / status changes
* Schedule phase additions / shifts
* Compliance callouts added or removed
* Atom counts by type (so a sudden drop signals a parser regression)

The tool is read-only — it does not modify either envelope.
Operate on JSON envelope files; the same code works on the
``00_envelope.json`` snapshot OrbitBrief-Core writes per
compile.

Usage:
    python tools/envelope_diff.py --before path/to/old.json --after path/to/new.json [--out diff.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load_envelope(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _index_by_filename(env: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(d.get("filename") or d.get("artifact_id") or ""): d
        for d in env.get("documents") or []
    }


def _entities_by_type(env: dict[str, Any], type_name: str) -> dict[str, dict[str, Any]]:
    """Returns ``{canonical_key: entity_dict}`` for one entity_type."""
    return {
        e.get("canonical_key", ""): e
        for e in env.get("entities") or []
        if e.get("entity_type") == type_name
    }


def _atoms_by_type(env: dict[str, Any]) -> Counter[str]:
    return Counter(a.get("atom_type", "") for a in env.get("atoms") or [])


def _money_values(env: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for atom in env.get("atoms") or []:
        for k in atom.get("entity_keys") or ():
            if isinstance(k, str) and k.startswith("money:"):
                try:
                    out.add(int(k.split(":", 1)[1]))
                except ValueError:
                    pass
    return out


def _risk_rows(env: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map risk_id → atom dict for every risk atom in the envelope."""
    out: dict[str, dict[str, Any]] = {}
    for atom in env.get("atoms") or []:
        if atom.get("atom_type") != "risk":
            continue
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or {}
        if not isinstance(cells, dict):
            continue
        rid = str(cells.get("risk_id") or "").strip()
        if rid:
            out[rid] = atom
    return out


def _schedule_phases(env: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pull schedule rows by their phase name."""
    out: dict[str, dict[str, Any]] = {}
    for atom in env.get("atoms") or []:
        structured = atom.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        cells = structured.get("canonical_cells") or structured.get("cells") or {}
        if not isinstance(cells, dict):
            continue
        name = str(
            cells.get("name")
            or cells.get("Name")
            or cells.get("phase")
            or cells.get("Phase")
            or ""
        )
        start = cells.get("start_date") or cells.get("Start Date") or ""
        end = cells.get("end_date") or cells.get("End Date") or ""
        if name and (start or end):
            out[name] = {"start": str(start), "end": str(end), "atom_id": atom.get("id", "")}
    return out


def render_diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Render the diff between two envelopes as a markdown report."""
    lines: list[str] = []

    before_id = before.get("project_id") or before.get("compile_id") or "before"
    after_id = after.get("project_id") or after.get("compile_id") or "after"
    lines.extend([
        "# Envelope diff",
        "",
        f"- **Before:** `{before_id}` ({before.get('generated_at', '?')})",
        f"- **After:**  `{after_id}` ({after.get('generated_at', '?')})",
        "",
    ])

    # ── Source files ─────────────────────────────────────────────
    b_files = _index_by_filename(before)
    a_files = _index_by_filename(after)
    added_files = sorted(set(a_files) - set(b_files))
    removed_files = sorted(set(b_files) - set(a_files))
    if added_files or removed_files:
        lines.append("## Source files")
        lines.append("")
        for f in added_files:
            lines.append(f"- **+ added:** `{f}`")
        for f in removed_files:
            lines.append(f"- **- removed:** `{f}`")
        lines.append("")

    # ── Atom counts by type ───────────────────────────────────────
    b_types = _atoms_by_type(before)
    a_types = _atoms_by_type(after)
    all_types = sorted(set(b_types) | set(a_types))
    delta_rows = [
        (t, b_types.get(t, 0), a_types.get(t, 0))
        for t in all_types
        if b_types.get(t, 0) != a_types.get(t, 0)
    ]
    if delta_rows:
        lines.append("## Atoms by type")
        lines.append("")
        lines.extend([
            "| Type | Before | After | Δ |",
            "|---|---:|---:|---:|",
        ])
        for t, bc, ac in delta_rows:
            delta = ac - bc
            sign = "+" if delta > 0 else ""
            lines.append(f"| {t} | {bc} | {ac} | {sign}{delta} |")
        lines.append("")

    # ── Sites ─────────────────────────────────────────────────────
    b_sites = _entities_by_type(before, "site")
    a_sites = _entities_by_type(after, "site")
    added_sites = sorted(set(a_sites) - set(b_sites))
    removed_sites = sorted(set(b_sites) - set(a_sites))
    if added_sites or removed_sites:
        lines.append("## Sites")
        lines.append("")
        for s in added_sites:
            lines.append(f"- **+ added:** `{s}` ({a_sites[s].get('canonical_name', '')})")
        for s in removed_sites:
            lines.append(f"- **- removed:** `{s}` ({b_sites[s].get('canonical_name', '')})")
        lines.append("")

    # ── Stakeholders ──────────────────────────────────────────────
    b_stakes = _entities_by_type(before, "stakeholder")
    a_stakes = _entities_by_type(after, "stakeholder")
    added_stakes = sorted(set(a_stakes) - set(b_stakes))
    removed_stakes = sorted(set(b_stakes) - set(a_stakes))
    if added_stakes or removed_stakes:
        lines.append("## Stakeholders")
        lines.append("")
        for s in added_stakes:
            lines.append(f"- **+ added:** `{s}` ({a_stakes[s].get('canonical_name', '')})")
        for s in removed_stakes:
            lines.append(f"- **- removed:** `{s}` ({b_stakes[s].get('canonical_name', '')})")
        lines.append("")

    # ── Money values ──────────────────────────────────────────────
    b_money = _money_values(before)
    a_money = _money_values(after)
    added_money = sorted(a_money - b_money, reverse=True)
    removed_money = sorted(b_money - a_money, reverse=True)
    if added_money or removed_money:
        lines.append("## Money values")
        lines.append("")
        for v in added_money[:20]:
            lines.append(f"- **+ added:** ${v:,}")
        if len(added_money) > 20:
            lines.append(f"  _… and {len(added_money) - 20} more_")
        for v in removed_money[:20]:
            lines.append(f"- **- removed:** ${v:,}")
        if len(removed_money) > 20:
            lines.append(f"  _… and {len(removed_money) - 20} more_")
        lines.append("")

    # ── Risk register ─────────────────────────────────────────────
    b_risks = _risk_rows(before)
    a_risks = _risk_rows(after)
    added_risks = sorted(set(a_risks) - set(b_risks))
    removed_risks = sorted(set(b_risks) - set(a_risks))
    changed_risks: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for rid in sorted(set(b_risks) & set(a_risks)):
        b_cells = (b_risks[rid].get("structured") or {}).get("canonical_cells") or {}
        a_cells = (a_risks[rid].get("structured") or {}).get("canonical_cells") or {}
        if b_cells != a_cells:
            changed_risks.append((rid, b_cells, a_cells))
    if added_risks or removed_risks or changed_risks:
        lines.append("## Risk register")
        lines.append("")
        for rid in added_risks:
            cells = (a_risks[rid].get("structured") or {}).get("canonical_cells") or {}
            lines.append(
                f"- **+ added:** **{rid}** — {cells.get('description','')} "
                f"({cells.get('likelihood','')}/{cells.get('impact','')})"
            )
        for rid in removed_risks:
            cells = (b_risks[rid].get("structured") or {}).get("canonical_cells") or {}
            lines.append(
                f"- **- removed:** **{rid}** — {cells.get('description','')}"
            )
        for rid, bc, ac in changed_risks:
            field_changes = [
                f"{k}: '{bc.get(k,'')}' → '{ac.get(k,'')}'"
                for k in sorted(set(bc) | set(ac))
                if bc.get(k) != ac.get(k)
            ]
            lines.append(f"- **~ updated:** **{rid}**")
            for fc in field_changes[:6]:
                lines.append(f"  - {fc}")
        lines.append("")

    # ── Schedule phases ───────────────────────────────────────────
    b_phases = _schedule_phases(before)
    a_phases = _schedule_phases(after)
    added_phases = sorted(set(a_phases) - set(b_phases))
    removed_phases = sorted(set(b_phases) - set(a_phases))
    shifted_phases: list[tuple[str, dict[str, str], dict[str, str]]] = []
    for p in sorted(set(b_phases) & set(a_phases)):
        if b_phases[p].get("start") != a_phases[p].get("start") or b_phases[p].get("end") != a_phases[p].get("end"):
            shifted_phases.append((p, b_phases[p], a_phases[p]))
    if added_phases or removed_phases or shifted_phases:
        lines.append("## Project schedule")
        lines.append("")
        for p in added_phases:
            d = a_phases[p]
            lines.append(f"- **+ added:** **{p}** ({d.get('start','?')} → {d.get('end','?')})")
        for p in removed_phases:
            d = b_phases[p]
            lines.append(f"- **- removed:** **{p}** ({d.get('start','?')} → {d.get('end','?')})")
        for p, bd, ad in shifted_phases:
            lines.append(
                f"- **~ shifted:** **{p}** — "
                f"start `{bd.get('start','?')}` → `{ad.get('start','?')}`, "
                f"end `{bd.get('end','?')}` → `{ad.get('end','?')}`"
            )
        lines.append("")

    if len(lines) <= 5:
        lines.append("_No PM-visible changes detected between the two envelopes._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="envelope_diff")
    p.add_argument("--before", required=True, type=Path, help="older envelope JSON")
    p.add_argument("--after", required=True, type=Path, help="newer envelope JSON")
    p.add_argument("--out", type=Path, help="output markdown path (defaults to stdout)")
    args = p.parse_args(argv)
    before = _load_envelope(args.before)
    after = _load_envelope(args.after)
    md = render_diff(before, after)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        sys.stderr.write(f"wrote {args.out}\n")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
