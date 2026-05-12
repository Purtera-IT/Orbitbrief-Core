"""``python -m orbitbrief_core.review_ui --artifacts <dir>`` — launch reviewer UI.

Lightweight uvicorn launcher. The optional ``[ui]`` extra installs
fastapi + uvicorn + jinja2 + python-multipart.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import uvicorn
except ImportError as exc:  # pragma: no cover - environmental
    raise SystemExit(
        "review_ui needs uvicorn. Install with: pip install -e '.[ui]'"
    ) from exc

from orbitbrief_core.review_ui import create_app_from_artifacts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orbitbrief_core.review_ui")
    p.add_argument(
        "--artifacts",
        required=True,
        help="Path to an orchestrator-produced artifacts directory",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    artifacts = Path(args.artifacts)
    if not artifacts.is_dir():
        print(f"artifacts directory not found: {artifacts}", file=sys.stderr)
        return 1

    app = create_app_from_artifacts(artifacts)
    print(
        f"OrbitBrief Reviewer serving artifacts at {artifacts}\n"
        f"  → http://{args.host}:{args.port}/queue",
        file=sys.stderr,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
