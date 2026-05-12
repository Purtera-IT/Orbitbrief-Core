#!/usr/bin/env python3
"""Convenience entrypoint: ``python compile_brief.py engagement.json --out artifacts/``.

Thin wrapper around ``python -m orbitbrief_core.orchestrator compile`` so
operators don't have to remember the module path.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the in-tree ``src/`` importable when running from a checkout.
_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.orchestrator.__main__ import main


if __name__ == "__main__":
    # Forward all argv to the orchestrator's compile command. If the
    # user already passed an explicit subcommand, respect it; otherwise
    # default to ``compile``.
    args = sys.argv[1:]
    if not args or args[0] not in {"compile"}:
        args = ["compile", *args]
    raise SystemExit(main(args))
