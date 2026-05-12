"""CLI: ``python -m orbitbrief_core.seam <envelope.json> [--out summary.json]``.

End-to-end smoke for the parser-os ↔ OrbitBrief seam:

1. Read an ``orbitbrief.input.v2`` envelope JSON file from disk
   (the one allowlisted raw read in OrbitBrief).
2. Validate it against :class:`EnvelopeV2`.
3. Run :func:`consume_envelope` to produce a deterministic summary.
4. Write the summary as JSON (default: stdout).

Exit codes:
    0  success
    1  envelope load / validation failure
    2  CLI usage error

Example:
    python -m orbitbrief_core.seam path/to/orbitbrief.input.json \\
        --out path/to/summary.json --top-n 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orbitbrief_core.seam.consumer import consume_envelope
from orbitbrief_core.seam.loader import EnvelopeLoadError, load_envelope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orbitbrief_core.seam",
        description=(
            "Validate an orbitbrief.input.v2 envelope and emit a deterministic "
            "OrbitBrief summary."
        ),
    )
    parser.add_argument(
        "envelope",
        type=Path,
        help="Path to the envelope JSON file (produced by parser-os).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path. Defaults to stdout.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Cap on top-entities / top-atoms / top-packets lists (default: 10).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent for pretty-printing (default: 2). Use 0 for compact.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        envelope = load_envelope(args.envelope)
    except EnvelopeLoadError as exc:
        cause = f": {exc.__cause__}" if exc.__cause__ else ""
        print(f"orbitbrief_core.seam: {exc}{cause}", file=sys.stderr)
        return 1

    summary = consume_envelope(
        envelope,
        top_n_entities=args.top_n,
        top_n_atoms=args.top_n,
        top_n_packets=args.top_n,
    )

    payload = summary.model_dump(mode="json")
    indent = args.indent if args.indent > 0 else None
    text = json.dumps(payload, indent=indent, sort_keys=False, ensure_ascii=False)

    if args.out is None:
        print(text)
    else:
        # Allowlisted write — see tools/check_no_raw_open.py.
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(
            f"orbitbrief_core.seam: wrote {summary.atom_count} atoms / "
            f"{summary.packet_count} packets summary to {args.out}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover — entry point
    raise SystemExit(main())
