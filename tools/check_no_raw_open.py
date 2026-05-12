"""Phase-0 invariants for the parser-os ↔ OrbitBrief seam.

Two checks live here:

1. **Raw filesystem reads** in ``orbitbrief_core`` are a contract
   violation — OrbitBrief must consume the ``orbitbrief.input.v2``
   envelope produced by parser-os, not raw files.

   This is enforced as a **ratchet**: today's legacy callers are pinned
   in ``.raw_open_baseline.json`` and the check fails on any *new* raw
   read added on top of that baseline. Phase 1+ will whittle the
   baseline down to zero as we migrate each module.

   Refresh the baseline (only when intentionally migrating) with:
       python tools/check_no_raw_open.py --update-baseline

2. **Parser-os internals** (``app.parsers.*``, ``app.segmentation.*``,
   etc.) must never be imported from ``orbitbrief_core``. This is
   zero-tolerance: any violation fails. ``import-linter`` cannot forbid
   subpackages of external packages, so we enforce it here statically.

Run it from CI: ``python tools/check_no_raw_open.py``.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "orbitbrief_core"
BASELINE_PATH = REPO_ROOT / "tools" / ".raw_open_baseline.json"

FORBIDDEN_BUILTINS = {"open"}
FORBIDDEN_ATTRS = {
    "open",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
}

# Modules where raw filesystem access is *legitimate by design*, not legacy
# debt. Distinct from the baseline (which is a "to migrate" list); these
# are permanent. Add sparingly with an inline justification.
# Paths are relative to ``SOURCE_ROOT``.
PERMANENT_ALLOWLIST: frozenset[str] = frozenset({
    # Phase 1A seam: the orbitbrief.input.v2 envelope JSON is the
    # OrbitBrief input contract. Reading it is the one allowed raw
    # read in OrbitBrief Core; everything else flows through the
    # typed envelope.
    "seam/loader.py",
    # Phase 1A CLI: writes the summary JSON when --out is passed.
    # Output is also part of the seam (a downstream artifact).
    "seam/__main__.py",
    # Phase 3 world model: reads the bundled domain_packs.yaml via
    # importlib.resources. That's reading packaged data shipped with
    # the wheel, not user input — semantically distinct from raw I/O.
    "world_model/registry.py",
    # Phase 7.5 briefing brains: reads the bundled briefing_configs.yaml
    # via importlib.resources. Same justification as world_model/registry.
    "brains/_briefing_config.py",
    # Phase 5 brains CLI: reads serialized BriefState + RetrievalBundle
    # JSON paths from argv. Inspection-only; production callers
    # invoke the brain class directly via the orchestrator.
    "brains/__main__.py",
    # Phase 6 review_runtime persistence: JSONL queue + training
    # log. These are explicit storage backends with their own
    # in-memory siblings — production callers pick one at construction.
    "review_runtime/queue.py",
    "review_runtime/training_log.py",
    # Phase 7 orchestrator: writes per-stage artifacts to disk and
    # reads the input envelope. This module IS the seam between the
    # in-process pipeline and the operator's filesystem.
    "orchestrator/artifacts.py",
    "orchestrator/pipeline.py",
    "orchestrator/__main__.py",
})

# Top-level parser-os modules that are the public seam. Anything outside
# this set, under the parser-os ``app.*`` namespace, is internal and
# off-limits.
PARSER_OS_PUBLIC_SEAM = {
    "app.core.schemas",
    "app.core.orbitbrief_envelope",
    "app.core.compiler",
    "app.core.manifest",
}

# Parser-os internal subpackages — zero tolerance.
PARSER_OS_FORBIDDEN_PREFIXES = (
    "app.parsers",
    "app.segmentation",
    "parser_os.parsers",
    "parser_os.segmentation",
)


# ────────────────────────────── visitors ───────────────────────────────


class RawIOFinder(ast.NodeVisitor):
    """Flag every ``open()``, ``Path.read_text()``, etc., call."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 (ast API)
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTINS:
            self.violations.append((node.lineno, f"raw {func.id}() call"))
        elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTRS:
            self.violations.append(
                (node.lineno, f".{func.attr}() call (likely Path/IO)")
            )
        self.generic_visit(node)


class ParserInternalsFinder(ast.NodeVisitor):
    """Flag any import that reaches into parser-os internals."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def _check(self, lineno: int, dotted: str) -> None:
        for prefix in PARSER_OS_FORBIDDEN_PREFIXES:
            if dotted == prefix or dotted.startswith(prefix + "."):
                self.violations.append((lineno, f"forbidden import: {dotted}"))
                return

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check(node.lineno, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self._check(node.lineno, node.module)


# ────────────────────────────── runner ─────────────────────────────────


def _scan(root: Path) -> tuple[set[str], list[tuple[str, int, str]]]:
    """Return (raw-IO offender file set, parser-internals violations)."""
    raw_io_files: set[str] = set()
    parser_internals: list[tuple[str, int, str]] = []

    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            print(f"WARN: failed to parse {rel}: {exc}", file=sys.stderr)
            continue

        raw = RawIOFinder()
        raw.visit(tree)
        if raw.violations:
            raw_io_files.add(rel)

        internals = ParserInternalsFinder()
        internals.visit(tree)
        for lineno, msg in internals.violations:
            parser_internals.append((rel, lineno, msg))

    return raw_io_files, parser_internals


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.is_file():
        return set()
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return set(data.get("raw_io_legacy_files", []))


def _write_baseline(files: set[str]) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_doc": (
            "Phase-0 ratchet baseline. Each entry is a module under "
            "src/orbitbrief_core/ that still reads raw files. New "
            "entries are forbidden — the check fails until the file is "
            "migrated to consume the orbitbrief.input.v2 envelope or "
            "removed. Refresh ONLY when migrating: "
            "`python tools/check_no_raw_open.py --update-baseline`."
        ),
        "raw_io_legacy_files": sorted(files),
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Snapshot the current raw-IO offender set into the baseline.",
    )
    args = parser.parse_args()

    if not SOURCE_ROOT.is_dir():
        print(f"FATAL: source root not found: {SOURCE_ROOT}", file=sys.stderr)
        return 2

    raw_io_files, parser_internals = _scan(SOURCE_ROOT)

    # Drop allowlisted (permanently legitimate) raw-IO holders from the
    # offender set BEFORE doing any baseline math — they should never
    # have been part of the baseline and should never trigger the
    # ratchet.
    raw_io_files -= PERMANENT_ALLOWLIST

    if args.update_baseline:
        _write_baseline(raw_io_files)
        print(
            f"Baseline refreshed: {len(raw_io_files)} legacy raw-IO files "
            f"recorded in {BASELINE_PATH.relative_to(REPO_ROOT)} "
            f"({len(PERMANENT_ALLOWLIST)} allowlisted)"
        )
        return 0

    baseline = _load_baseline()
    new_raw = sorted(raw_io_files - baseline)
    fixed_raw = sorted(baseline - raw_io_files)

    failed = False

    if new_raw:
        failed = True
        print("FAIL: new raw-file reads detected (not in Phase-0 baseline):\n")
        for rel in new_raw:
            print(f"  + {rel}")
        print(
            "\nOrbitBrief must consume the orbitbrief.input.v2 envelope, "
            "not raw files. Migrate this module to the envelope or, if "
            "migrating an existing legacy module, refresh the baseline "
            "with: python tools/check_no_raw_open.py --update-baseline"
        )
        print()

    if parser_internals:
        failed = True
        print(
            f"FAIL: parser-os internals referenced from orbitbrief_core "
            f"({len(parser_internals)} violation(s)):\n"
        )
        for rel, lineno, msg in parser_internals:
            print(f"  {rel}:{lineno}  {msg}")
        print(
            "\nOnly the public parser-os seam is allowed: "
            f"{sorted(PARSER_OS_PUBLIC_SEAM)}"
        )
        print()

    if fixed_raw:
        # Not a failure, but flag it so the team can shrink the baseline.
        print(
            f"NOTE: {len(fixed_raw)} legacy file(s) no longer read raw "
            "files. Shrink the baseline:"
        )
        for rel in fixed_raw:
            print(f"  - {rel}")
        print(
            "\nRun: python tools/check_no_raw_open.py --update-baseline"
        )
        print()

    if failed:
        return 1

    print(
        f"check_no_raw_open: OK "
        f"(raw-IO baseline: {len(baseline)} legacy file(s) pinned, "
        f"{len(PERMANENT_ALLOWLIST)} allowlisted, "
        f"parser-internals: zero violations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
