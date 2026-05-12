"""Phase-1 invariant: envelope → load → re-emit must be byte-identical.

The evidence runtime's whole point is to be a *pure substrate* — it
can't silently mutate, reorder, or drop any field of the producer's
envelope. If this regresses, downstream Phase-2 retrieval and
Phase-3 calibration will see drift across runs.

We don't literally use ``STRESS_*`` because those fixtures are
labels-only (no compileable artifacts). The COPPER_001-backed
mixed package is the closest real-world equivalent: PDF + XLSX +
transcript + email through every parser-os family.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.evidence_runtime import EvidenceRuntime
from orbitbrief_core.evidence_runtime.store import canonical_json


def test_envelope_roundtrips_dict_equal(mixed_envelope: dict[str, Any]) -> None:
    """``to_envelope_dict`` returns exactly the input dict (modulo timestamps)."""
    runtime = EvidenceRuntime.from_envelope(mixed_envelope)
    try:
        out = runtime.to_envelope_dict()
    finally:
        runtime.close()

    # ``generated_at`` is the only non-deterministic surface in
    # parser-os envelopes (wall clock at compile). Spec exempts it.
    expected = dict(mixed_envelope)
    actual = dict(out)
    expected["generated_at"] = "<TIMESTAMP>"
    actual["generated_at"] = "<TIMESTAMP>"
    assert actual == expected


def test_envelope_roundtrips_text_byte_identical(
    mixed_envelope: dict[str, Any],
) -> None:
    """The canonical JSON text round-trips byte-for-byte (modulo timestamps)."""
    runtime = EvidenceRuntime.from_envelope(mixed_envelope)
    try:
        actual_text = runtime.to_envelope_text()
    finally:
        runtime.close()

    expected_text = canonical_json(mixed_envelope)
    # Strip the timestamp line from both sides before comparing.
    actual = _strip_timestamp(actual_text)
    expected = _strip_timestamp(expected_text)
    assert actual == expected, _diff(expected, actual)


def test_load_from_path_then_roundtrip(mixed_envelope_path: Path) -> None:
    """Loading from disk → store → re-emit also round-trips."""
    runtime = EvidenceRuntime.from_envelope_path(mixed_envelope_path)
    try:
        out = runtime.to_envelope_dict()
    finally:
        runtime.close()
    src = json.loads(mixed_envelope_path.read_text(encoding="utf-8"))
    src["generated_at"] = out["generated_at"] = "<TIMESTAMP>"
    assert out == src


def test_indexed_columns_match_envelope_rows(
    mixed_envelope: dict[str, Any],
) -> None:
    """Spot-check: per-row indexed columns reflect the envelope content.

    If the ingest path drops or reorders rows, the count assertion
    fires immediately rather than waiting for a downstream
    correctness regression.
    """
    runtime = EvidenceRuntime.from_envelope(mixed_envelope)
    try:
        store = runtime.store
        key = runtime.default_key.to_envelope_key()  # type: ignore[union-attr]
        atom_count = store.connection.execute(
            "SELECT COUNT(*) FROM atoms WHERE project_id=? AND compile_id=?",
            [key.project_id, key.compile_id],
        ).fetchone()[0]
        packet_count = store.connection.execute(
            "SELECT COUNT(*) FROM packets WHERE project_id=? AND compile_id=?",
            [key.project_id, key.compile_id],
        ).fetchone()[0]
        edge_count = store.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE project_id=? AND compile_id=?",
            [key.project_id, key.compile_id],
        ).fetchone()[0]
    finally:
        runtime.close()

    assert atom_count == len(mixed_envelope["atoms"])
    assert packet_count == len(mixed_envelope["packets"])
    assert edge_count == len(mixed_envelope["edges"])


# ────────────────────────────── helpers ────────────────────────────────


def _strip_timestamp(text: str) -> str:
    """Drop the single line containing ``"generated_at"`` so timestamps don't fail diffs."""
    return "\n".join(
        line for line in text.splitlines() if '"generated_at"' not in line
    )


def _diff(expected: str, actual: str) -> str:
    """Compact diff message for the byte-identity assertion."""
    import difflib

    diff = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="expected",
            tofile="actual",
            lineterm="",
            n=2,
        )
    )
    return "\n".join(diff[:80])
