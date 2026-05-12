"""Phase-8 reviewer UI: FastAPI + HTMX over the review queue.

Lightweight by design — server-rendered HTML, HTMX for interactive
bits (decision form + queue refresh). No SPA framework, no build
step, no JS bundling. Reviewers run:

    python -m orbitbrief_core.review_ui --artifacts <artifacts_dir>

…and get a queue page they can open in a browser to accept /
reject / edit items the calibrator routed to them.

Architectural rules:

* The UI may import :mod:`orbitbrief_core.review_runtime`,
  :mod:`orbitbrief_core.composer`, :mod:`orbitbrief_core.calibrator`
  (for the :class:`Verdict` enum). It MUST NOT import the runtime,
  the seam, retrieval, or any brain runner.
* FastAPI / Jinja2 / uvicorn are optional dependencies; the
  package raises a clear error at import time when they're missing.

Install with:

    pip install -e '.[ui]'
"""
from __future__ import annotations

from orbitbrief_core.review_ui.app import (
    build_app,
    create_app_from_artifacts,
)
from orbitbrief_core.review_ui.context import ReviewContext

__all__ = [
    "ReviewContext",
    "build_app",
    "create_app_from_artifacts",
]
