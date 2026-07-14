#!/usr/bin/env python3
"""Prove evidence-first customer_questions on deal 010101 tip artifacts.

Usage:
  PYTHONPATH=src python tools/prove_customer_questions_010101.py \\
    --envelope path/to/latest_envelope.json \\
    --before-handoff path/to/latest_PM_HANDOFF.json \\
    --out-dir /tmp/qprove
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.pm_handoff.models import GapCard, SiteSummary
from orbitbrief_core.pm_handoff.question_engine import build_customer_questions


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--envelope", type=Path, required=True)
    p.add_argument("--before-handoff", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    before = json.loads(args.before_handoff.read_text(encoding="utf-8"))
    envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
    sites = [
        SiteSummary(
            name=str(s.get("name") or "?"),
            kind=str(s.get("kind") or "physical_site"),
            publishable=bool(s.get("publishable")),
        )
        for s in (before.get("sites") or [])
        if isinstance(s, dict)
    ]
    gaps = [
        GapCard(
            rule_id=str(g.get("rule_id") or "unknown"),
            domain_id=str(g.get("domain_id") or "global"),
            domain_label=str(g.get("domain_label") or ""),
            label=str(g.get("label") or ""),
            severity=str(g.get("severity") or "warning"),
            message=str(g.get("message") or ""),
            suggested_open_question=str(g.get("suggested_open_question") or ""),
        )
        for g in (before.get("gaps") or [])
        if isinstance(g, dict)
    ]

    cards, meta = build_customer_questions(
        gaps=gaps,
        sites=sites,
        envelope=envelope,
        feedback_events=[],
        cap=8,
    )

    before_qs = [
        {
            "rule_id": q.get("rule_id"),
            "question": q.get("suggested_open_question") or q.get("message"),
        }
        for q in (before.get("customer_questions") or [])
    ]
    after_qs = [
        {
            "rule_id": c.rule_id,
            "question": c.suggested_open_question,
            "severity": c.severity,
            "domain_id": c.domain_id,
        }
        for c in cards
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "deal_id": before.get("case_id"),
        "project_mode": meta.get("project_mode"),
        "sources": meta.get("sources"),
        "before_count": len(before_qs),
        "after_count": len(after_qs),
        "before": before_qs,
        "after": after_qs,
    }
    (args.out_dir / "questions_before_after.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Patch a copy of the handoff for local inspection / optional upload.
    patched = dict(before)
    patched["customer_questions"] = [
        {
            "rule_id": c.rule_id,
            "domain_id": c.domain_id,
            "domain_label": c.domain_label,
            "label": c.label,
            "severity": c.severity,
            "message": c.message,
            "suggested_open_question": c.suggested_open_question,
            "observed_summary": c.observed_summary,
        }
        for c in cards
    ]
    metrics = dict(patched.get("metrics") or {})
    metrics["project_mode"] = meta.get("project_mode")
    metrics["customer_question_engine"] = meta
    patched["metrics"] = metrics
    (args.out_dir / "PM_HANDOFF_questions_patched.json").write_text(
        json.dumps(patched, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("=== BEFORE ===")
    for q in before_qs:
        print("-", q["rule_id"], "::", (q["question"] or "")[:140])
    print()
    print("=== AFTER ===")
    print("mode=", meta.get("project_mode"), "sources=", meta.get("sources"))
    for q in after_qs:
        print("-", q["rule_id"], "::", q["question"])
    print()
    print("Wrote", args.out_dir / "questions_before_after.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
