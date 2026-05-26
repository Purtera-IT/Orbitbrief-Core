"""Post-close hook — captures the learning signal from a closed deal.

Run this when a PM marks a deal as won / lost / no-decision. It:

1. Reads ``PM_HANDOFF.json`` + ``polish_report.json`` from the
   artifacts dir.
2. Lets the PM record outcome + post-mortem (CLI args or stdin
   prompts).
3. Optionally ingests a JSONL of PM decisions
   (``accepted_atom_ids[]``, ``rejected_atom_ids[]``, …) if the
   reviewer UI exported one.
4. Builds a :class:`LearningRecord` and appends to the ledger.

Usage::

    python tools/close_deal.py \\
        --artifacts /azure/blob/quotes/Q-12345/pm_handoff \\
        --outcome won \\
        --final-margin-pct 22.4 \\
        --post-mortem "TSA badging delays cost us 2 weeks; flag earlier"

    # With PM-decisions JSONL exported from the review UI:
    python tools/close_deal.py \\
        --artifacts ... --outcome won \\
        --decisions /azure/blob/quotes/Q-12345/pm_decisions.jsonl

The ledger path defaults to ``$ORBITBRIEF_LEARNING_LEDGER`` or
``<artifacts>/.orbitbrief_learning_ledger.jsonl``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from orbitbrief_core.learning import (  # noqa: E402
    LearningLedger,
    PmDecisionRecord,
)
from orbitbrief_core.learning.learning_ledger import build_record_from_handoff  # noqa: E402


def _load_decisions(path: Path | None) -> list[PmDecisionRecord]:
    if path is None or not path.exists():
        return []
    out: list[PmDecisionRecord] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(
                PmDecisionRecord(
                    target_kind=str(row.get("target_kind", "")),
                    target_id=str(row.get("target_id", "")),
                    action=str(row.get("action", "")),
                    raw_text=str(row.get("raw_text", "")),
                    final_text=str(row.get("final_text", "")),
                    reviewer=str(row.get("reviewer", "")),
                )
            )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--artifacts",
        type=Path,
        required=True,
        help="Path to compile output directory containing PM_HANDOFF.json + polish_report.json",
    )
    p.add_argument(
        "--outcome",
        choices=["won", "lost", "no_decision"],
        required=True,
        help="Final outcome of the deal",
    )
    p.add_argument(
        "--final-margin-pct",
        type=float,
        help="Actual realized margin (overrides PM_HANDOFF.margin_view.margin_pct)",
    )
    p.add_argument(
        "--post-mortem",
        default="",
        help="Free-text notes (what went right, what went wrong, what to flag next time)",
    )
    p.add_argument(
        "--decisions",
        type=Path,
        help="Optional JSONL of PM decisions (one per line, see PmDecisionRecord shape)",
    )
    p.add_argument(
        "--closed-at",
        help="ISO date the deal closed (default: today)",
    )
    p.add_argument(
        "--ledger",
        type=Path,
        help=f"Output ledger path (default: $ORBITBRIEF_LEARNING_LEDGER or <artifacts>/.orbitbrief_learning_ledger.jsonl)",
    )
    args = p.parse_args(argv)

    handoff_path = args.artifacts / "PM_HANDOFF.json"
    if not handoff_path.exists():
        print(f"[close_deal] PM_HANDOFF.json not found at {handoff_path}", file=sys.stderr)
        return 2
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))

    polish_path = args.artifacts / "polish_report.json"
    polish_report = (
        json.loads(polish_path.read_text(encoding="utf-8"))
        if polish_path.exists()
        else None
    )

    record = build_record_from_handoff(
        handoff,
        outcome=args.outcome,
        final_margin_pct=args.final_margin_pct,
        pm_decisions=_load_decisions(args.decisions),
        post_mortem=args.post_mortem,
        closed_at=args.closed_at,
        polish_report=polish_report,
    )

    if args.ledger:
        ledger_path = args.ledger
    elif os.environ.get("ORBITBRIEF_LEARNING_LEDGER"):
        ledger_path = Path(os.environ["ORBITBRIEF_LEARNING_LEDGER"])
    else:
        ledger_path = args.artifacts / ".orbitbrief_learning_ledger.jsonl"

    ledger = LearningLedger(path=ledger_path)
    ledger.append(record)

    print(
        f"[close_deal] appended LearningRecord for {record.case_id} "
        f"(outcome={record.outcome}, margin={record.final_margin_pct:.1f}%, "
        f"{len(record.pm_decisions)} pm_decisions) -> {ledger_path}",
        flush=True,
    )
    print(f"[close_deal] ledger now contains {ledger.record_count()} records", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
