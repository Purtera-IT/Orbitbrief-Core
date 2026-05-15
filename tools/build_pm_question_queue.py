#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from orbitbrief_core.pm_handoff import build_portfolio_handoff
from orbitbrief_core.pm_handoff.business_labels import SEVERITY_SORT


def main() -> int:
    parser = argparse.ArgumentParser(description="Export OrbitBrief customer clarification questions as PM tracker CSV.")
    parser.add_argument("--cases-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    for handoff in build_portfolio_handoff(args.cases_root):
        for gap in sorted(handoff.customer_questions, key=lambda g: (SEVERITY_SORT.get(g.severity, 9), g.domain_label, g.label)):
            rows.append(
                {
                    "case_id": handoff.case_id,
                    "case_status": handoff.status,
                    "severity": gap.severity,
                    "domain": gap.domain_label,
                    "rule_id": gap.rule_id,
                    "label": gap.label,
                    "customer_question": gap.suggested_open_question or gap.message,
                    "owner": "",
                    "due_date": "",
                    "customer_answer": "",
                    "pm_notes": "",
                    "resolved": "no",
                    "false_positive": "no",
                    "rule_upgrade_requested": "no",
                }
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["case_id"]
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} PM questions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
