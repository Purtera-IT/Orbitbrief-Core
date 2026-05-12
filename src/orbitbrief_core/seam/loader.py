"""Load + validate ``orbitbrief.input.v2`` envelopes from disk or memory.

The ``open()`` call inside :func:`load_envelope` is the *only*
allowed raw-file read in ``orbitbrief_core``: the envelope JSON is
the OrbitBrief input contract. Phase-0 ``check_no_raw_open.py``
allowlists this module by path. All other inputs flow through the
typed envelope.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from orbitbrief_core.seam.envelope import EnvelopeV2


class EnvelopeLoadError(ValueError):
    """Raised when an envelope file is missing, malformed, or fails schema validation.

    Always wraps the underlying cause (FileNotFoundError, JSONDecodeError,
    ValidationError) so callers can see what went wrong without
    swallowing the parser-side detail.
    """


def load_envelope_dict(payload: dict[str, Any]) -> EnvelopeV2:
    """Validate an in-memory envelope dict against the v2 schema.

    Use this when an envelope arrives via something other than disk
    (HTTP, queue, in-process call). It is the single entry point used
    by both :func:`load_envelope` and any future transport adapter,
    so the validation rule lives in exactly one place.

    Raises:
        EnvelopeLoadError: if the payload doesn't match
            :class:`EnvelopeV2`. The underlying ``ValidationError`` is
            attached as ``__cause__``.
    """
    try:
        return EnvelopeV2.model_validate(payload)
    except ValidationError as exc:
        raise EnvelopeLoadError(
            "envelope payload failed orbitbrief.input.v2 validation"
        ) from exc


def load_envelope(path: Path | str) -> EnvelopeV2:
    """Read a JSON envelope file from disk and validate it.

    The path is the only raw-file read OrbitBrief is allowed to
    perform. Everything downstream consumes the resulting
    :class:`EnvelopeV2` object — never the raw bytes.

    Raises:
        EnvelopeLoadError: missing file, unreadable JSON, or
            v2-schema mismatch. Underlying cause is preserved on
            ``__cause__``.
    """
    p = Path(path)
    if not p.is_file():
        raise EnvelopeLoadError(f"envelope file not found: {p}")
    try:
        # Allowlisted raw read — see module docstring + tools/check_no_raw_open.py.
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvelopeLoadError(f"failed to read envelope file {p}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnvelopeLoadError(f"envelope file {p} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EnvelopeLoadError(
            f"envelope file {p} top-level must be a JSON object, got {type(payload).__name__}"
        )
    return load_envelope_dict(payload)
