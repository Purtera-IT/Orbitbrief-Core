"""Run Orbitbrief-Core substrate (no LLM) over pre-compiled envelopes.

Reads ``orbitbrief.input.json`` from each ``<case_id>.orbitbrief/``
under ``--envelopes-root`` and runs ``compile_brief.py <envelope>
--out <out>/<case_id>/`` per case. Substrate-only by default — no
Ollama required.

Each case ends up with the substrate artifacts the regression gate
+ corpus metrics report read from:

    <out>/<case_id>/01_pack_prior.json
    <out>/<case_id>/02_site_reality.json
    <out>/<case_id>/inspection_report.json
    <out>/<case_id>/00_envelope.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--envelopes-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--per-case-timeout", type=int, default=180)
    p.add_argument("--clean", action="store_true")
    args = p.parse_args(argv)

    if args.clean and args.out_dir.exists():
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    compile_brief = repo_root / "compile_brief.py"

    summaries: list[dict] = []
    envelope_dirs = sorted(
        x for x in args.envelopes_root.iterdir() if x.is_dir() and x.suffix == ".orbitbrief"
    )
    print(f"running {len(envelope_dirs)} cases through Core substrate", file=sys.stderr)

    for env_dir in envelope_dirs:
        case_id = env_dir.name.replace(".orbitbrief", "")
        envelope = env_dir / "orbitbrief.input.json"
        if not envelope.is_file():
            summaries.append({"case_id": case_id, "status": "missing_envelope"})
            continue

        case_out = args.out_dir / case_id
        case_out.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(compile_brief),
            str(envelope),
            "--out",
            str(case_out),
            "--quiet",
        ]
        started = time.monotonic()
        status = "ok"
        err = ""
        try:
            r = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=args.per_case_timeout,
                check=False,
            )
            if r.returncode != 0:
                status = "error"
                err = (r.stderr or "")[-1500:]
        except subprocess.TimeoutExpired:
            status = "timeout"
            err = f"timed out after {args.per_case_timeout}s"
        elapsed = time.monotonic() - started

        summaries.append(
            {
                "case_id": case_id,
                "status": status,
                "elapsed_s": round(elapsed, 2),
                "envelope_used": str(envelope),
                "error_tail": err if status != "ok" else "",
            }
        )
        print(
            f"  [{status:7s}] {case_id} ({round(elapsed, 2)}s)",
            file=sys.stderr,
        )

    summary_path = args.out_dir / "_substrate_summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    ok = sum(1 for s in summaries if s["status"] == "ok")
    print(f"\nok={ok}/{len(summaries)}  summary={summary_path}", file=sys.stderr)
    return 0 if ok == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
