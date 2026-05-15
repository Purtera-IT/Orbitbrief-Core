#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbitbrief_core.pm_handoff.render_html import render_pm_executive_html, render_solution_architect_html
from orbitbrief_core.pm_handoff import (
    build_pm_handoff,
    build_portfolio_handoff,
    render_pm_handoff_html,
    render_pm_handoff_markdown,
    render_pm_executive_markdown,
    render_solution_architect_markdown,
    render_portfolio_html,
    render_portfolio_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PM/solution-architect-facing OrbitBrief handoff reports.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case-dir", type=Path)
    group.add_argument("--cases-root", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--format", choices=["all", "md", "html", "json"], default="all")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.case_dir:
        handoff = build_pm_handoff(args.case_dir)
        _write_case_outputs(handoff, args.out_dir, args.format)
        print(f"Wrote PM handoff for {handoff.case_id} to {args.out_dir}")
        return 0

    handoffs = build_portfolio_handoff(args.cases_root)
    if not handoffs:
        raise SystemExit(f"No compiled cases found under {args.cases_root}")
    for handoff in handoffs:
        _write_case_outputs(handoff, args.out_dir / handoff.case_id, args.format)
    if args.format in {"all", "md"}:
        (args.out_dir / "PM_PORTFOLIO_DASHBOARD.md").write_text(render_portfolio_markdown(handoffs), encoding="utf-8")
    if args.format in {"all", "html"}:
        (args.out_dir / "PM_PORTFOLIO_DASHBOARD.html").write_text(render_portfolio_html(handoffs), encoding="utf-8")
    if args.format in {"all", "json"}:
        (args.out_dir / "PM_PORTFOLIO_DASHBOARD.json").write_text(json.dumps([h.to_dict() for h in handoffs], indent=2), encoding="utf-8")
    print(f"Wrote PM portfolio handoff for {len(handoffs)} case(s) to {args.out_dir}")
    return 0


def _write_case_outputs(handoff, out_dir: Path, fmt: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt in {"all", "md"}:
        (out_dir / "PM_HANDOFF.md").write_text(render_pm_handoff_markdown(handoff), encoding="utf-8")
        (out_dir / "PM_EXECUTIVE_SUMMARY.md").write_text(render_pm_executive_markdown(handoff), encoding="utf-8")
        (out_dir / "SA_REVIEW_PACKET.md").write_text(render_solution_architect_markdown(handoff), encoding="utf-8")
    if fmt in {"all", "html"}:
        (out_dir / "PM_HANDOFF.html").write_text(render_pm_handoff_html(handoff), encoding="utf-8")
        (out_dir / "PM_EXECUTIVE_SUMMARY.html").write_text(render_pm_executive_html(handoff), encoding="utf-8")
        (out_dir / "SA_REVIEW_PACKET.html").write_text(render_solution_architect_html(handoff), encoding="utf-8")
    if fmt in {"all", "json"}:
        (out_dir / "PM_HANDOFF.json").write_text(json.dumps(handoff.to_dict(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
