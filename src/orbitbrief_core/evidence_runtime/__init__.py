"""Phase 1 — Evidence Runtime: typed substrate over parser-os outputs.

A read-only, no-LLM storage and query layer that:

1. Loads a validated ``orbitbrief.input.v2`` envelope (from
   :mod:`orbitbrief_core.seam`) into an embedded DuckDB store.
2. Exposes a typed query API (``get_atom``, ``get_entity``,
   ``packets_for``, ``contradictions_for``) for downstream layers
   (retrieval, brains, composers, validator, calibrator).
3. Bridges provenance back to parser-os via :func:`replay_source`,
   so any atom can be re-verified against original artifact bytes.

Design rules (enforced by ``test_no_inference``):
* No model / LLM / embedding / vector / inference imports anywhere
  under :mod:`orbitbrief_core.evidence_runtime`.
* No raw input-file reads (PDFs, DOCX, …) — provenance replay
  delegates to ``parser_os.app.core.source_replay`` which holds the
  per-format verifiers.

The single public entry point is :class:`EvidenceRuntime`. Construct
it via :meth:`EvidenceRuntime.from_envelope` (in-memory) or
:meth:`EvidenceRuntime.from_envelope_path` (disk).
"""
from __future__ import annotations

from orbitbrief_core.evidence_runtime.contradictions import (
    ContradictionPair,
    contradictions_for,
)
from orbitbrief_core.evidence_runtime.provenance import (
    ReplayResult,
    replay_source,
)
from orbitbrief_core.evidence_runtime.runtime import (
    EvidenceRuntime,
    RuntimeKey,
)
from orbitbrief_core.evidence_runtime.store import EvidenceStore

__all__ = [
    "ContradictionPair",
    "EvidenceRuntime",
    "EvidenceStore",
    "ReplayResult",
    "RuntimeKey",
    "contradictions_for",
    "replay_source",
]
