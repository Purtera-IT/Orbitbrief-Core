"""Drive parser-os compile across a corpus with a per-case timeout.

macOS doesn't ship ``timeout``; this is the portable replacement that
also captures per-case status in a JSON summary so the boss-facing
report can show exactly which cases compiled and which timed out.

Usage::

    python tools/run_corpus_with_timeout.py \\
        --raw-cases /tmp/orbitbrief_raw_cases \\
        --out-dir /tmp/parser_os_results \\
        --parser-os ~/dev/purtera/parser-os-repo \\
        --per-case-timeout 240
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run_one(
    *, case_dir: Path, out_dir: Path, parser_os: Path, timeout_s: int
) -> dict:
    case_id = case_dir.name
    json_out = out_dir / f"{case_id}.json"
    orbit_out = out_dir / f"{case_id}.orbitbrief"
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "compile",
        str(case_dir),
        "--out",
        str(json_out),
        "--orbitbrief-out",
        str(orbit_out),
        "--allow-errors",
        "--allow-unverified-receipts",
        "--no-cache",
    ]
    started = time.monotonic()
    status = "ok"
    err = ""
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(parser_os),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if completed.returncode != 0:
            status = "error"
            err = (completed.stderr or "")[-2000:]
    except subprocess.TimeoutExpired:
        status = "timeout"
        err = f"timed out after {timeout_s}s"
    elapsed = time.monotonic() - started

    return {
        "case_id": case_id,
        "status": status,
        "elapsed_s": round(elapsed, 2),
        "out_json_exists": json_out.is_file(),
        "envelope_dir_exists": orbit_out.is_dir(),
        "error_tail": err if status != "ok" else "",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-cases", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--parser-os", type=Path, required=True)
    p.add_argument("--per-case-timeout", type=int, default=240)
    p.add_argument("--clean", action="store_true")
    args = p.parse_args(argv)

    if args.clean and args.out_dir.exists():
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    cases = sorted(x for x in args.raw_cases.iterdir() if x.is_dir())
    print(f"compiling {len(cases)} cases (timeout={args.per_case_timeout}s/case)", file=sys.stderr)
    for case in cases:
        s = run_one(
            case_dir=case,
            out_dir=args.out_dir,
            parser_os=args.parser_os,
            timeout_s=args.per_case_timeout,
        )
        summaries.append(s)
        print(
            f"  [{s['status']:7s}] {s['case_id']} ({s['elapsed_s']}s)",
            file=sys.stderr,
        )

    summary_path = args.out_dir / "_compile_summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")

    ok = sum(1 for s in summaries if s["status"] == "ok")
    timed = sum(1 for s in summaries if s["status"] == "timeout")
    err = sum(1 for s in summaries if s["status"] == "error")
    print(
        f"\ndone: ok={ok} timeout={timed} error={err}  summary={summary_path}",
        file=sys.stderr,
    )
    return 0 if timed == 0 and err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
