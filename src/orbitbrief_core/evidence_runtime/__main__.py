"""CLI for the Phase-1 evidence runtime.

Two subcommands:

    python -m orbitbrief_core.evidence_runtime load \\
        --envelope path/to/orbitbrief.input.json \\
        [--db path/to/runtime.duckdb]

    python -m orbitbrief_core.evidence_runtime query packets \\
        [--db path/to/runtime.duckdb | --envelope path/to/orbitbrief.input.json] \\
        [--family scope_inclusion] [--anchor SCOPE_001]

``load`` ingests an envelope into a (file or in-memory) DuckDB store.
``query`` materializes rows from an existing store, or — for one-shot
smoke testing — re-ingests an envelope into an in-memory store first.

Exit codes:
    0  success
    1  envelope load / store failure
    2  CLI usage error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime
from orbitbrief_core.evidence_runtime.store import EvidenceStore
from orbitbrief_core.seam.loader import EnvelopeLoadError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orbitbrief_core.evidence_runtime",
        description="OrbitBrief evidence_runtime CLI (load / query).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_load = sub.add_parser("load", help="Ingest an envelope into the store.")
    p_load.add_argument("--envelope", required=True, type=Path)
    p_load.add_argument(
        "--db",
        type=Path,
        default=None,
        help="DuckDB file path (default: in-memory; nothing persists).",
    )
    p_load.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Directory holding original input files (for later replay).",
    )

    p_query = sub.add_parser("query", help="Read rows from the store.")
    q_sub = p_query.add_subparsers(dest="entity", required=True)

    p_packets = q_sub.add_parser("packets", help="List packets matching filters.")
    p_packets.add_argument("--db", type=Path, default=None)
    p_packets.add_argument(
        "--envelope",
        type=Path,
        default=None,
        help=(
            "If --db is omitted, ingest this envelope into a temp "
            "in-memory store before querying."
        ),
    )
    p_packets.add_argument("--family", default=None)
    p_packets.add_argument("--anchor", default=None)
    p_packets.add_argument("--status", default=None)

    p_atom = q_sub.add_parser("atom", help="Look up one atom by id.")
    p_atom.add_argument("--db", type=Path, default=None)
    p_atom.add_argument("--envelope", type=Path, default=None)
    p_atom.add_argument("--id", required=True)

    p_contra = q_sub.add_parser(
        "contradictions", help="Contradiction edges touching an entity or atom."
    )
    p_contra.add_argument("--db", type=Path, default=None)
    p_contra.add_argument("--envelope", type=Path, default=None)
    p_contra.add_argument("--entity", default=None)
    p_contra.add_argument("--atom-id", default=None)

    return parser


def _runtime_from_args(args: argparse.Namespace) -> EvidenceRuntime:
    """Resolve --db / --envelope into an EvidenceRuntime.

    Precedence: an existing DuckDB file is opened read-only-ish and
    its first stored envelope is used as the default key. Otherwise
    we ingest the supplied --envelope into an in-memory store.
    """
    db_path: Path | None = getattr(args, "db", None)
    envelope_path: Path | None = getattr(args, "envelope", None)

    if db_path is not None and db_path.exists():
        store = EvidenceStore.connect(db_path)
        keys = store.list_envelopes()
        if not keys:
            store.close()
            raise SystemExit(
                f"orbitbrief_core.evidence_runtime: db {db_path} has no envelopes"
            )
        from orbitbrief_core.evidence_runtime.runtime import RuntimeKey

        return EvidenceRuntime(
            store,
            default_key=RuntimeKey(
                project_id=keys[0].project_id, compile_id=keys[0].compile_id
            ),
        )

    if envelope_path is None:
        raise SystemExit(
            "orbitbrief_core.evidence_runtime: provide --db (existing) or --envelope"
        )
    return EvidenceRuntime.from_envelope_path(
        envelope_path, db_path=db_path
    )


def _cmd_load(args: argparse.Namespace) -> int:
    try:
        runtime = EvidenceRuntime.from_envelope_path(
            args.envelope, db_path=args.db, artifact_dir=args.artifact_dir
        )
    except EnvelopeLoadError as exc:
        cause = f": {exc.__cause__}" if exc.__cause__ else ""
        print(f"orbitbrief_core.evidence_runtime: {exc}{cause}", file=sys.stderr)
        return 1

    key = runtime.default_key
    assert key is not None
    print(
        f"loaded project_id={key.project_id} compile_id={key.compile_id} "
        f"into {'in-memory' if args.db is None else args.db}",
        file=sys.stderr,
    )
    runtime.close()
    return 0


def _cmd_query_packets(args: argparse.Namespace) -> int:
    runtime = _runtime_from_args(args)
    try:
        rows = runtime.packets_for(
            family=args.family, anchor=args.anchor, status=args.status
        )
    finally:
        runtime.close()
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def _cmd_query_atom(args: argparse.Namespace) -> int:
    runtime = _runtime_from_args(args)
    try:
        atom = runtime.get_atom(args.id)
    finally:
        runtime.close()
    if atom is None:
        print(
            f"orbitbrief_core.evidence_runtime: no atom with id={args.id}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(atom, indent=2, ensure_ascii=False))
    return 0


def _cmd_query_contradictions(args: argparse.Namespace) -> int:
    if (args.entity is None) == (args.atom_id is None):
        print(
            "orbitbrief_core.evidence_runtime: pass exactly one of --entity / --atom-id",
            file=sys.stderr,
        )
        return 2
    runtime = _runtime_from_args(args)
    try:
        pairs = runtime.contradictions_for(entity=args.entity, atom_id=args.atom_id)
    finally:
        runtime.close()
    payload = [
        {
            "edge": p.edge,
            "from_atom": p.from_atom,
            "to_atom": p.to_atom,
        }
        for p in pairs
    ]
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "load":
        return _cmd_load(args)
    if args.cmd == "query":
        if args.entity == "packets":
            return _cmd_query_packets(args)
        if args.entity == "atom":
            return _cmd_query_atom(args)
        if args.entity == "contradictions":
            return _cmd_query_contradictions(args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
