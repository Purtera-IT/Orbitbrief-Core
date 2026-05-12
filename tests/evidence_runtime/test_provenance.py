"""Phase-1 provenance contract: every atom can be replayed against its source.

A *replay* takes the atom's ``raw_text`` + ``locator`` and re-checks
them against the bytes parser-os pulled from the original artifact.
We don't require ``"verified"`` for every atom — some locators are
unsupported by the verifier (e.g. atoms anchored to a structural
block with no line range). What we *do* require is:

* Every atom returns a structured :class:`ReplayResult`.
* Every atom carries enough provenance (artifact_id + locator) for
  the runtime to *attempt* a replay (status ``"failed"`` only ever
  comes from real bytes mismatch, never from missing metadata).
* The substrate never raises on replay — bad atoms surface as
  ``"failed"`` or ``"unsupported"``.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from orbitbrief_core.evidence_runtime import EvidenceRuntime
from orbitbrief_core.evidence_runtime.provenance import ReplayResult


def test_every_atom_returns_replay_result(
    mixed_envelope: dict[str, Any], mixed_artifact_dir: Path
) -> None:
    """``replay_source`` never raises and always returns a ReplayResult."""
    runtime = EvidenceRuntime.from_envelope(
        mixed_envelope, artifact_dir=mixed_artifact_dir
    )
    try:
        results: list[ReplayResult] = []
        for atom in mixed_envelope["atoms"]:
            results.append(runtime.replay_source(atom["id"]))
    finally:
        runtime.close()

    assert len(results) == len(mixed_envelope["atoms"])
    assert all(isinstance(r, ReplayResult) for r in results)
    assert all(r.atom_id and r.artifact_id for r in results)


def test_replay_status_distribution_is_sane(
    mixed_envelope: dict[str, Any], mixed_artifact_dir: Path
) -> None:
    """At least *some* atoms should verify against bytes.

    On a freshly-compiled mixed package, the bytes are identical to
    what the parser saw, so we expect a non-trivial ``verified``
    bucket. If this drops to zero the bridge to parser-os is broken.
    """
    runtime = EvidenceRuntime.from_envelope(
        mixed_envelope, artifact_dir=mixed_artifact_dir
    )
    try:
        statuses = Counter(
            runtime.replay_source(a["id"]).status
            for a in mixed_envelope["atoms"]
        )
    finally:
        runtime.close()

    assert sum(statuses.values()) == len(mixed_envelope["atoms"])
    assert statuses["verified"] >= 1, (
        f"expected at least one verified atom, got distribution: {dict(statuses)}"
    )


def test_replay_without_artifact_dir_returns_unsupported(
    mixed_envelope: dict[str, Any],
) -> None:
    """When the source bytes aren't available, we degrade gracefully — not raise."""
    runtime = EvidenceRuntime.from_envelope(mixed_envelope)  # no artifact_dir
    try:
        first_atom_id = mixed_envelope["atoms"][0]["id"]
        result = runtime.replay_source(first_atom_id)
    finally:
        runtime.close()
    assert result.status == "unsupported"
    assert "artifact_dir" in result.reason or "not found" in result.reason


def test_replay_unknown_atom_id_raises_keyerror(
    mixed_envelope: dict[str, Any], mixed_artifact_dir: Path
) -> None:
    """An unknown atom_id is a programmer error → fail loud."""
    import pytest

    runtime = EvidenceRuntime.from_envelope(
        mixed_envelope, artifact_dir=mixed_artifact_dir
    )
    try:
        with pytest.raises(KeyError, match="unknown atom_id"):
            runtime.replay_source("atm_does_not_exist")
    finally:
        runtime.close()
