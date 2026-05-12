"""Shared types for the retrieval substrate.

The :class:`RetrievalHit` is the **only** thing that crosses the
retrieval boundary outward. It deliberately carries no text — just
ids and scores — so downstream callers (brains, composers in later
phases) cannot bypass provenance by reading retrieved bodies
directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# Stable string tags for index kinds. Strings (not enums) so they
# survive JSON round-trips and inter-process IPC without ceremony.
INDEX_KIND_EVIDENCE = "evidence"
INDEX_KIND_PACKET = "packet"
INDEX_KIND_CLAIM = "claim"
INDEX_KIND_EXAMPLE = "example"

IndexKind = Literal["evidence", "packet", "claim", "example"]


@dataclass(frozen=True)
class RetrievalHit:
    """One scored hit returned from any retrieval index.

    Attributes:
        id: stable identifier of the hit (atom_id, packet_id, …) —
            re-hydrate via :class:`EvidenceRuntime` to get the body.
        score: similarity / rerank score. Convention: higher is
            better. For cosine distance we return ``1 - distance``.
        kind: which index produced the hit. Lets callers route
            re-hydration without smuggling type-tagged ids.
        metadata: small, JSON-serializable bag for index-specific
            facets (e.g. packet ``family``, atom ``atom_type``).
            **Never put text bodies here** — that defeats the whole
            point of the bounded contract.
    """

    id: str
    score: float
    kind: IndexKind
    metadata: dict[str, Any] = field(default_factory=dict)
