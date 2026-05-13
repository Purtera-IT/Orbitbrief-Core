#!/usr/bin/env python3
"""``compile_corpus.py <corpus_root>/ --out <results_dir>/`` — batch run.

Compiles every case under ``<corpus_root>`` (each subdirectory =
one case) through the OrbitBrief pipeline, writes per-case
artifacts under ``<results_dir>/<case_id>/``, then aggregates
everything into a single corpus dashboard at
``<results_dir>/corpus_dashboard.html``.

Examples::

    # Substrate-only sweep across the test corpus (no LLM, ~15s/case)
    python compile_corpus.py \\
      /Users/purtera/dev/purtera/testing/managed_services_sow_artifact_pack \\
      --out /tmp/orbitbrief_corpus_results

    # Full pipeline including brains (slow; ~6 min/case on Mac)
    python compile_corpus.py <corpus_root> --out <results_dir> --ollama

    # Just specific cases
    python compile_corpus.py <corpus_root> --out <results_dir> --ollama \\
      --cases COPPER_001_SPRING_LAKE_AUDITORIUM,STRESS_NATOMAS_WIRELESS

    # Skip cases that already have artifacts (incremental)
    python compile_corpus.py <corpus_root> --out <results_dir> --skip-existing

    # Re-aggregate the dashboard without re-running the pipeline
    python compile_corpus.py <corpus_root> --out <results_dir> --aggregate-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.orchestrator.corpus import build_corpus_report
from orbitbrief_core.orchestrator.corpus_html import render_corpus_html


def _list_cases(corpus_root: Path) -> list[Path]:
    """Every immediate subdirectory of corpus_root that has > 0 files in it."""
    out: list[Path] = []
    for p in sorted(corpus_root.iterdir()):
        if not p.is_dir():
            continue
        # Skip top-level docs / manifest dirs.
        if p.name.startswith(".") or p.name.startswith("00_"):
            continue
        if any(child.is_file() for child in p.iterdir()):
            out.append(p)
    return out


def _run_case(
    case_dir: Path,
    out_dir: Path,
    *,
    ollama: bool,
    chat_model: str,
    escalated_model: str,
    quiet_parser: bool,
) -> tuple[bool, float, str]:
    """Run one case through compile_brief.py, return (success, seconds, log)."""
    start = time.perf_counter()
    args = [
        sys.executable,
        str(_REPO_ROOT / "compile_brief.py"),
        str(case_dir),
        "--out",
        str(out_dir),
        "--quiet",
    ]
    if ollama:
        args.extend(
            [
                "--ollama",
                "--chat-model",
                chat_model,
                "--escalated-model",
                escalated_model,
            ]
        )
    if quiet_parser:
        args.append("--quiet-parser")
    proc = subprocess.run(args, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    success = proc.returncode == 0
    log_tail = (proc.stdout or "")[-400:] + (proc.stderr or "")[-1200:]
    return success, elapsed, log_tail


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="compile_corpus.py",
        description="Batch-compile a directory of OrbitBrief cases + generate a dashboard.",
    )
    p.add_argument("corpus_root", help="Directory of per-case subdirectories")
    p.add_argument("--out", required=True, help="Output results directory")
    p.add_argument(
        "--ollama",
        action="store_true",
        help="Run the LLM stages (planner + brains). Without this, only "
        "substrate stages run (parser-os + pack_prior + site_reality + "
        "retrieval bundles + inspection report) — fast (~15 s/case).",
    )
    p.add_argument("--chat-model", default="qwen3:14b")
    p.add_argument("--escalated-model", default="qwen3:14b")
    p.add_argument(
        "--quiet-parser",
        action="store_true",
        default=True,
        help="Suppress parser-os replay-error stderr noise (default true).",
    )
    p.add_argument(
        "--cases",
        help="Comma-separated case ids to run (default: all cases in corpus_root).",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip cases whose artifact dir already has a manifest.json (incremental run).",
    )
    p.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Don't run the pipeline; just re-build the dashboard from existing artifacts.",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Delete the output directory before running (default: keep + overwrite per case).",
    )
    args = p.parse_args(argv)

    corpus_root = Path(args.corpus_root)
    out_root = Path(args.out)

    if not corpus_root.is_dir():
        print(f"compile_corpus: corpus root not found: {corpus_root}", file=sys.stderr)
        return 1
    if args.clean and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.aggregate_only:
        print(
            f"compile_corpus: aggregate-only mode — building dashboard from {out_root}",
            file=sys.stderr,
        )
        return _write_dashboard(out_root, ran=[], skipped=[], failed=[], total_s=0.0)

    cases = _list_cases(corpus_root)
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
        cases = [c for c in cases if c.name in wanted]

    if not cases:
        print("compile_corpus: no cases to run.", file=sys.stderr)
        return 1

    print(
        f"compile_corpus: {len(cases)} case(s) to run "
        f"(ollama={'yes' if args.ollama else 'no'}, output={out_root})",
        file=sys.stderr,
    )
    ran: list[tuple[str, float]] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    total_start = time.perf_counter()

    for i, case_dir in enumerate(cases, 1):
        case_id = case_dir.name
        case_out = out_root / case_id
        if args.skip_existing and (case_out / "manifest.json").is_file():
            print(f"  [{i}/{len(cases)}] {case_id}: skip (manifest exists)", file=sys.stderr)
            skipped.append(case_id)
            continue
        print(f"  [{i}/{len(cases)}] {case_id}: running…", end="", flush=True, file=sys.stderr)
        success, elapsed, log = _run_case(
            case_dir,
            case_out,
            ollama=args.ollama,
            chat_model=args.chat_model,
            escalated_model=args.escalated_model,
            quiet_parser=args.quiet_parser,
        )
        marker = " OK" if success else " FAILED"
        print(f"  {marker} ({elapsed:.1f}s)", file=sys.stderr)
        if success:
            ran.append((case_id, elapsed))
        else:
            failed.append((case_id, log))
            # Still record what we got so the dashboard can show partial results.

    total_s = time.perf_counter() - total_start
    return _write_dashboard(out_root, ran=ran, skipped=skipped, failed=failed, total_s=total_s)


def _write_dashboard(
    out_root: Path,
    *,
    ran: list[tuple[str, float]],
    skipped: list[str],
    failed: list[tuple[str, str]],
    total_s: float,
) -> int:
    print("compile_corpus: building corpus dashboard…", file=sys.stderr)
    report = build_corpus_report(out_root)
    json_path = out_root / "corpus_report.json"
    html_path = out_root / "corpus_dashboard.html"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    html_path.write_text(render_corpus_html(report), encoding="utf-8")

    print("", file=sys.stderr)
    print(f"compile_corpus: dashboard written:", file=sys.stderr)
    print(f"  → {html_path}", file=sys.stderr)
    print(f"  → {json_path}", file=sys.stderr)
    print(f"compile_corpus: {len(ran)} case(s) ran, {len(skipped)} skipped, {len(failed)} failed", file=sys.stderr)
    if total_s > 0:
        print(f"compile_corpus: total runtime {total_s:.1f}s", file=sys.stderr)
    if failed:
        print("compile_corpus: failed cases:", file=sys.stderr)
        for cid, log in failed[:5]:
            print(f"  - {cid}: {log[-200:]!r}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"open {html_path}", file=sys.stderr)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
