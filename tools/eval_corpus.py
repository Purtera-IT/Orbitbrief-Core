#!/usr/bin/env python3
"""eval_corpus.py — regression-baseline harness for the OrbitBrief pipeline.

Runs ``pm_handoff.sh`` over a glob of cases, captures the manifest +
brain-output stats per case, and writes a single JSON snapshot you can
diff against a known-good baseline. Optional ``--baseline`` mode
compares the run against a saved snapshot and exits non-zero on any
regression in:

* Brains that ran (any pack that used to emit but doesn't anymore)
* Brain item counts per pack (any drop ≥ 30 %)
* Verified-atom health (drop > 5 percentage points)
* PM handoff status (green → yellow / red is a regression)
* Pipeline fallbacks (any new fallback)

Cheap, single-file, no external deps beyond stdlib + pyyaml.

Usage::

    # First run — capture a baseline.
    python3 tools/eval_corpus.py \\
        --cases /Users/.../parser-os-repo/real_data_cases/COPPER_001_*  \\
        --out /tmp/orbitbrief_eval/$(date +%Y%m%dT%H%M%SZ) \\
        --save-baseline tests/baselines/eval_corpus_baseline.json

    # Subsequent runs — compare.
    python3 tools/eval_corpus.py \\
        --cases /Users/.../parser-os-repo/real_data_cases/COPPER_*  \\
        --out /tmp/orbitbrief_eval/$(date +%Y%m%dT%H%M%SZ) \\
        --baseline tests/baselines/eval_corpus_baseline.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ────────────────────────────── data shapes ────────────────────────────


@dataclass
class CaseSummary:
    """One per-case snapshot. The shape used for both the run snapshot
    and the saved baseline file."""
    case_id: str
    case_dir: str
    out_dir: str
    elapsed_s: float
    exit_code: int
    brains_run: list[str] = field(default_factory=list)
    active_packs: list[str] = field(default_factory=list)
    items_per_brain: dict[str, int] = field(default_factory=dict)
    fallback_brains: list[str] = field(default_factory=list)
    skipped_brains_no_chat: bool = False
    stage_status_counts: dict[str, int] = field(default_factory=dict)
    pm_status: str = "unknown"
    pm_blocker_count: int = 0
    pm_warning_count: int = 0
    verification_health_pct: float = 0.0
    verification_failed_count: int = 0
    verification_atom_total: int = 0
    error: str = ""


# ────────────────────────────── helpers ────────────────────────────────


def _safe_load(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summarize_case(case_dir: Path, out_dir: Path, elapsed_s: float, exit_code: int) -> CaseSummary:
    summary = CaseSummary(
        case_id=case_dir.name,
        case_dir=str(case_dir),
        out_dir=str(out_dir),
        elapsed_s=round(elapsed_s, 2),
        exit_code=exit_code,
    )
    manifest = _safe_load(out_dir / "manifest.json") or {}
    summary.brains_run = sorted(manifest.get("brains_run") or [])
    summary.active_packs = sorted(manifest.get("active_packs") or [])
    summary.skipped_brains_no_chat = bool(manifest.get("skipped_brains_no_chat"))
    summary.stage_status_counts = dict(manifest.get("stage_status_counts") or {})

    # Per-brain item counts + fallback flag.
    brain_dir = out_dir / "40_brain_outputs"
    if brain_dir.is_dir():
        sections = (
            "scope_overview",
            "detailed_scope_of_services",
            "deliverables",
            "assumptions",
            "customer_responsibilities",
            "out_of_scope",
            "risks_or_dependencies",
            "completion_criteria",
            "open_items",
        )
        for f in sorted(brain_dir.glob("*.json")):
            data = _safe_load(f) or {}
            pack = f.stem
            n_items = sum(len(data.get(s) or []) for s in sections)
            summary.items_per_brain[pack] = n_items
            if data.get("fallback_used"):
                summary.fallback_brains.append(pack)

    # PM handoff status + gap counts.
    pm = _safe_load(out_dir / "PM_HANDOFF.json") or {}
    summary.pm_status = str(pm.get("status") or "unknown")
    gaps = pm.get("gaps") or []
    summary.pm_blocker_count = sum(1 for g in gaps if g.get("severity") == "blocker")
    summary.pm_warning_count = sum(1 for g in gaps if g.get("severity") == "warning")

    # Verification telemetry (lives inside 90_inspection_report.json).
    insp = _safe_load(out_dir / "90_inspection_report.json") or {}
    ver = insp.get("verification") or {}
    summary.verification_health_pct = float(ver.get("health_pct") or 0.0)
    summary.verification_failed_count = int(ver.get("failed_count") or 0)
    summary.verification_atom_total = int(ver.get("atom_total") or 0)

    return summary


def _run_one_case(
    pm_handoff_sh: Path, case_dir: Path, out_root: Path, env_overrides: dict[str, str]
) -> CaseSummary:
    out_dir = out_root / case_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    env = {**os.environ, **env_overrides}
    proc = subprocess.run(
        [str(pm_handoff_sh), str(case_dir), str(out_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.perf_counter() - start
    summary = _summarize_case(case_dir, out_dir, elapsed, proc.returncode)
    if proc.returncode != 0:
        # Tail of stderr is the most useful operator hint when a run dies.
        summary.error = (proc.stderr or proc.stdout or "")[-600:]
    # Also drop a per-case stdout/stderr alongside the artifacts.
    (out_dir / "_eval_stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    (out_dir / "_eval_stderr.log").write_text(proc.stderr or "", encoding="utf-8")
    return summary


# ────────────────────────────── regression diff ────────────────────────


def _compare_to_baseline(
    current: list[CaseSummary], baseline: list[dict[str, Any]]
) -> list[str]:
    """Return a list of regression strings; empty list = no regressions."""
    by_id = {b.get("case_id"): b for b in baseline}
    regressions: list[str] = []
    for cur in current:
        prev = by_id.get(cur.case_id)
        if prev is None:
            # New case — not a regression but worth noting.
            continue
        # 1. Missing brains.
        prev_brains = set(prev.get("brains_run") or [])
        cur_brains = set(cur.brains_run)
        missing = sorted(prev_brains - cur_brains)
        if missing:
            regressions.append(
                f"{cur.case_id}: brains stopped running: {missing}"
            )
        # 2. Item-count drops ≥ 30 %.
        prev_items = prev.get("items_per_brain") or {}
        for pack, prev_n in prev_items.items():
            cur_n = cur.items_per_brain.get(pack, 0)
            if prev_n >= 5 and cur_n <= prev_n * 0.7:
                regressions.append(
                    f"{cur.case_id}: {pack} brain items dropped {prev_n} → {cur_n}"
                )
        # 3. Verified-health drop > 5 pp.
        prev_health = float(prev.get("verification_health_pct") or 0.0)
        if prev_health and cur.verification_health_pct + 5.0 < prev_health:
            regressions.append(
                f"{cur.case_id}: parser health dropped "
                f"{prev_health:.1f}% → {cur.verification_health_pct:.1f}%"
            )
        # 4. PM status got worse.
        rank = {"green": 0, "yellow": 1, "red": 2, "unknown": 1}
        if rank.get(cur.pm_status, 1) > rank.get(prev.get("pm_status") or "unknown", 1):
            regressions.append(
                f"{cur.case_id}: PM status regressed "
                f"{prev.get('pm_status')} → {cur.pm_status}"
            )
        # 5. New fallbacks.
        new_fb = sorted(set(cur.fallback_brains) - set(prev.get("fallback_brains") or []))
        if new_fb:
            regressions.append(
                f"{cur.case_id}: new brain fallbacks: {new_fb}"
            )
    return regressions


# ────────────────────────────── main ───────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval_corpus.py", description=__doc__)
    p.add_argument(
        "--cases",
        required=True,
        nargs="+",
        help="One or more case dirs (or globs). Each is run through pm_handoff.sh.",
    )
    p.add_argument("--out", required=True, help="Root output directory for this run.")
    p.add_argument(
        "--pm-handoff",
        default=None,
        help="Path to pm_handoff.sh (default: sibling of this script).",
    )
    p.add_argument(
        "--baseline",
        default=None,
        help="Compare current run to this baseline JSON; exit non-zero on regression.",
    )
    p.add_argument(
        "--save-baseline",
        default=None,
        help="Write the current run as a new baseline JSON.",
    )
    p.add_argument(
        "--ollama-base-url", default=None, help="Override OLLAMA_BASE_URL for the runs."
    )
    p.add_argument("--chat-model", default=None, help="Override CHAT_MODEL.")
    p.add_argument(
        "--escalated-model", default=None, help="Override ESCALATED_MODEL."
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep running remaining cases even if one fails.",
    )
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    pm_handoff_sh = Path(args.pm_handoff) if args.pm_handoff else (repo_root / "pm_handoff.sh")
    if not pm_handoff_sh.is_file():
        sys.exit(f"eval_corpus: pm_handoff.sh not found at {pm_handoff_sh}")
    if not os.access(pm_handoff_sh, os.X_OK):
        sys.exit(f"eval_corpus: {pm_handoff_sh} is not executable")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    # Resolve case globs.
    case_dirs: list[Path] = []
    for pattern in args.cases:
        path = Path(pattern)
        if path.is_dir():
            case_dirs.append(path)
            continue
        # glob — expand against cwd.
        matches = sorted(Path().glob(pattern))
        if not matches:
            print(f"eval_corpus: no matches for {pattern!r}", file=sys.stderr)
        case_dirs.extend(p for p in matches if p.is_dir())
    if not case_dirs:
        sys.exit("eval_corpus: no case dirs resolved from --cases")

    env_overrides: dict[str, str] = {}
    if args.ollama_base_url:
        env_overrides["OLLAMA_BASE_URL"] = args.ollama_base_url
    if args.chat_model:
        env_overrides["CHAT_MODEL"] = args.chat_model
    if args.escalated_model:
        env_overrides["ESCALATED_MODEL"] = args.escalated_model

    print(f"eval_corpus: {len(case_dirs)} case(s), out={out_root}")
    summaries: list[CaseSummary] = []
    overall_start = time.perf_counter()
    for i, case_dir in enumerate(case_dirs, start=1):
        print(
            f"eval_corpus: [{i}/{len(case_dirs)}] {case_dir.name} — "
            "running pm_handoff.sh ...",
            flush=True,
        )
        summary = _run_one_case(pm_handoff_sh, case_dir, out_root, env_overrides)
        summaries.append(summary)
        status_word = "ok" if summary.exit_code == 0 else "FAIL"
        n_items_total = sum(summary.items_per_brain.values())
        print(
            f"eval_corpus: [{i}/{len(case_dirs)}] {case_dir.name}: "
            f"{status_word} in {summary.elapsed_s:.1f}s — "
            f"brains={summary.brains_run or '[]'} items={n_items_total} "
            f"pm={summary.pm_status} health={summary.verification_health_pct:.1f}%",
            flush=True,
        )
        if summary.exit_code != 0 and not args.continue_on_error:
            print(
                f"eval_corpus: aborting after first failure "
                f"(use --continue-on-error to run all cases anyway).",
                file=sys.stderr,
            )
            break

    overall_elapsed = time.perf_counter() - overall_start
    snapshot = {
        "generated_at": _ts(),
        "elapsed_s": round(overall_elapsed, 2),
        "case_count": len(summaries),
        "cases": [asdict(s) for s in summaries],
    }
    snapshot_path = out_root / "eval_summary.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"eval_corpus: snapshot → {snapshot_path}")

    # Save-baseline path.
    if args.save_baseline:
        bp = Path(args.save_baseline)
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps(snapshot["cases"], indent=2), encoding="utf-8")
        print(f"eval_corpus: baseline saved → {bp}")

    # Compare path.
    exit_code = 0
    if args.baseline:
        bp = Path(args.baseline)
        baseline = _safe_load(bp)
        if baseline is None:
            print(
                f"eval_corpus: baseline not found / unreadable: {bp}",
                file=sys.stderr,
            )
            return 2
        if not isinstance(baseline, list):
            print(
                f"eval_corpus: baseline {bp} is not a list of case summaries",
                file=sys.stderr,
            )
            return 2
        regressions = _compare_to_baseline(summaries, baseline)
        if regressions:
            print("eval_corpus: REGRESSIONS detected:", file=sys.stderr)
            for r in regressions:
                print(f"  - {r}", file=sys.stderr)
            exit_code = 1
        else:
            print("eval_corpus: no regressions vs baseline.")

    # Top-level summary line.
    print(
        f"eval_corpus: {len(summaries)} case(s) in {overall_elapsed:.1f}s — "
        f"ok={sum(1 for s in summaries if s.exit_code == 0)} "
        f"fail={sum(1 for s in summaries if s.exit_code != 0)}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
