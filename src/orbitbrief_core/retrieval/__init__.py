"""Phase 2 — Retrieval substrate.

Four indices over the typed evidence runtime:

* :class:`EvidenceIndex` — atom-level. "find atoms similar to X."
* :class:`PacketIndex` — packet-level. "find findings about Y."
* :class:`ClaimIndex` — claim-level (atoms whose ``atom_type`` is
  scope_item / quantity / constraint / exclusion / compliance —
  i.e. assertable claims).
* :class:`ExampleIndex` — precedent / few-shot examples for brain
  prompting (Phase 4).

All four expose the same minimal contract — :class:`RetrievalHit`
(id + score + kind + metadata). **No text bodies cross the
retrieval boundary.** Callers re-hydrate text via
``EvidenceRuntime.get_atom`` etc. This keeps brains honest:
they can't bypass provenance by stuffing raw retrieved snippets
into prompts.

Backends:

* Storage: DuckDB + ``vss`` extension (HNSW + cosine). Single file
  per project (multiple compile_ids supported), 4 tables, one HNSW
  index per table.
* Embedding / reranking: any :class:`InferenceClient` from
  :mod:`orbitbrief_core.inference`. The ``DeterministicHashEmbedder``
  test stub has no inference dependency at all.
"""
from __future__ import annotations

from orbitbrief_core.retrieval.base import (
    INDEX_KIND_CLAIM,
    INDEX_KIND_EVIDENCE,
    INDEX_KIND_EXAMPLE,
    INDEX_KIND_PACKET,
    IndexKind,
    RetrievalHit,
)
from orbitbrief_core.retrieval.claim_index import (
    CLAIM_ATOM_TYPES,
    ClaimIndex,
)
from orbitbrief_core.retrieval.embedder import (
    DeterministicHashEmbedder,
    Embedder,
    RemoteVllmEmbedder,
)
from orbitbrief_core.retrieval.evidence_index import EvidenceIndex
from orbitbrief_core.retrieval.example_index import (
    ExampleIndex,
    ExampleRecord,
)
from orbitbrief_core.retrieval.packet_index import PacketIndex
from orbitbrief_core.retrieval.reranker import (
    IdentityReranker,
    RemoteVllmReranker,
    Reranker,
)
from orbitbrief_core.retrieval.store import (
    RetrievalStore,
    RetrievalStoreConfig,
)

__all__ = [
    "CLAIM_ATOM_TYPES",
    "ClaimIndex",
    "DeterministicHashEmbedder",
    "Embedder",
    "EvidenceIndex",
    "ExampleIndex",
    "ExampleRecord",
    "IdentityReranker",
    "INDEX_KIND_CLAIM",
    "INDEX_KIND_EVIDENCE",
    "INDEX_KIND_EXAMPLE",
    "INDEX_KIND_PACKET",
    "IndexKind",
    "PacketIndex",
    "RemoteVllmEmbedder",
    "RemoteVllmReranker",
    "Reranker",
    "RetrievalHit",
    "RetrievalStore",
    "RetrievalStoreConfig",
]
