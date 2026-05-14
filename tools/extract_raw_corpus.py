"""Extract a raw-only corpus from a handoff bundle.

The handoff bundle ``cases/<CASE_ID>/`` folders contain ``raw/`` plus
generated outputs (``lineage/``, ``extraction/``, ``synthesis/``,
``brief.md``, reports). If you compile that whole folder through
parser-os, the parser may ingest generated outputs and contaminate
results.

This script copies ONLY the raw artifacts from each case so a clean
``parser-os batch-compile`` or ``compile_corpus.py`` run sees only
the original intake.

Usage::

    python tools/extract_raw_corpus.py \\
        /path/to/orbitbrief_corpus_handoff \\
        --out /tmp/orbitbrief_raw_cases
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="extract_raw_corpus.py")
    p.add_argument("handoff", help="Path to an orbitbrief_corpus_handoff bundle root")
    p.add_argument("--out", required=True, help="Output raw-only corpus directory")
    p.add_argument(
        "--clean",
        action="store_true",
        help="Delete --out before extracting (default: skip existing cases)",
    )
    args = p.parse_args(argv)

    src_root = Path(args.handoff) / "cases"
    if not src_root.is_dir():
        print(f"extract_raw_corpus: not a handoff bundle (no cases/ dir): {args.handoff}", file=sys.stderr)
        return 1

    dst_root = Path(args.out)
    if args.clean and dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    n = 0
    for case in sorted(src_root.iterdir()):
        raw = case / "raw"
        if not raw.is_dir():
            continue
        dst = dst_root / case.name
        if dst.exists() and not args.clean:
            continue
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        for p in raw.iterdir():
            if p.is_file():
                shutil.copy2(p, dst / p.name)
            elif p.is_dir():
                shutil.copytree(p, dst / p.name)
        n += 1

    print(f"extract_raw_corpus: wrote {n} case(s) to {dst_root}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
