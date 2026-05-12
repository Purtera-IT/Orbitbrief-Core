"""Phase-2 retrieval fixtures.

Cross-suite fixtures (mixed_envelope, etc.) live in the root
``tests/conftest.py``; this file defines retrieval-only ones.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.evidence_runtime import EvidenceRuntime
from orbitbrief_core.retrieval import (
    DeterministicHashEmbedder,
    RetrievalStore,
    RetrievalStoreConfig,
)


# Embedding dim for tests. Big enough to avoid hash collisions on
# small corpora; small enough to keep build cost near zero.
TEST_EMBED_DIM = 128


@pytest.fixture
def hash_embedder() -> DeterministicHashEmbedder:
    return DeterministicHashEmbedder(dim=TEST_EMBED_DIM)


@pytest.fixture
def retrieval_store() -> RetrievalStore:
    """Fresh in-memory retrieval store, dim aligned to ``hash_embedder``."""
    store = RetrievalStore.connect(RetrievalStoreConfig(dim=TEST_EMBED_DIM))
    yield store
    store.close()


@pytest.fixture
def loaded_runtime(mixed_envelope) -> EvidenceRuntime:
    rt = EvidenceRuntime.from_envelope(mixed_envelope)
    yield rt
    rt.close()
