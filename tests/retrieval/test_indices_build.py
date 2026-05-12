"""Phase-2 substrate test: every index builds and counts match the runtime.

If a row in the runtime doesn't make it into the corresponding
index — or if a vector row exists with no source — downstream
search will return phantom hits. This test pins the no-orphan
invariant.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.evidence_runtime import EvidenceRuntime
from orbitbrief_core.retrieval import (
    INDEX_KIND_CLAIM,
    INDEX_KIND_EVIDENCE,
    INDEX_KIND_PACKET,
    CLAIM_ATOM_TYPES,
    ClaimIndex,
    DeterministicHashEmbedder,
    EvidenceIndex,
    PacketIndex,
    RetrievalStore,
)


def test_evidence_index_count_matches_envelope(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """Every atom in the envelope produces exactly one row in vec_evidence."""
    idx = EvidenceIndex(retrieval_store, hash_embedder)
    written = idx.build(loaded_runtime)
    expected = len(mixed_envelope["atoms"])
    assert written == expected
    key = loaded_runtime.default_key
    assert key is not None
    assert (
        retrieval_store.count(
            INDEX_KIND_EVIDENCE,
            project_id=key.project_id,
            compile_id=key.compile_id,
        )
        == expected
    )


def test_packet_index_count_matches_envelope(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    idx = PacketIndex(retrieval_store, hash_embedder)
    written = idx.build(loaded_runtime)
    expected = len(mixed_envelope["packets"])
    assert written == expected
    key = loaded_runtime.default_key
    assert key is not None
    assert (
        retrieval_store.count(
            INDEX_KIND_PACKET,
            project_id=key.project_id,
            compile_id=key.compile_id,
        )
        == expected
    )


def test_claim_index_only_indexes_claim_atom_types(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """Claim index drops atoms whose ``atom_type`` isn't in :data:`CLAIM_ATOM_TYPES`."""
    idx = ClaimIndex(retrieval_store, hash_embedder)
    written = idx.build(loaded_runtime)
    expected = sum(
        1
        for a in mixed_envelope["atoms"]
        if a.get("atom_type") in CLAIM_ATOM_TYPES
    )
    assert written == expected, (
        f"claim index wrote {written}, expected {expected}; "
        f"atom_type distribution: "
        f"{[a.get('atom_type') for a in mixed_envelope['atoms']]}"
    )


def test_no_orphan_ids_across_indices(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """Every ref_id stored in evidence/packet/claim resolves to a real envelope row."""
    EvidenceIndex(retrieval_store, hash_embedder).build(loaded_runtime)
    PacketIndex(retrieval_store, hash_embedder).build(loaded_runtime)
    ClaimIndex(retrieval_store, hash_embedder).build(loaded_runtime)

    key = loaded_runtime.default_key
    assert key is not None

    atom_ids = {a["id"] for a in mixed_envelope["atoms"]}
    packet_ids = {p["id"] for p in mixed_envelope["packets"]}

    for ref_id in retrieval_store.iter_ref_ids(
        INDEX_KIND_EVIDENCE,
        project_id=key.project_id,
        compile_id=key.compile_id,
    ):
        assert ref_id in atom_ids, f"orphan in evidence index: {ref_id}"

    for ref_id in retrieval_store.iter_ref_ids(
        INDEX_KIND_PACKET,
        project_id=key.project_id,
        compile_id=key.compile_id,
    ):
        assert ref_id in packet_ids, f"orphan in packet index: {ref_id}"

    for ref_id in retrieval_store.iter_ref_ids(
        INDEX_KIND_CLAIM,
        project_id=key.project_id,
        compile_id=key.compile_id,
    ):
        assert ref_id in atom_ids, f"orphan in claim index: {ref_id}"


def test_search_returns_only_id_and_score(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """RetrievalHit must NEVER include a ``text`` body — bounded-IO contract."""
    idx = PacketIndex(retrieval_store, hash_embedder)
    idx.build(loaded_runtime)
    if not mixed_envelope["packets"]:
        pytest.skip("no packets in envelope to search against")
    hits = idx.search("scope", top_k=5)
    assert hits, "expected at least one packet hit for query 'scope'"
    for hit in hits:
        assert hit.id
        assert isinstance(hit.score, float)
        assert hit.kind == "packet"
        # Bounded-IO: nothing in metadata should be a body.
        for v in hit.metadata.values():
            if isinstance(v, str):
                assert len(v) < 200, (
                    f"metadata value too long ({len(v)} chars) — "
                    "looks like a body slipped through the bounded-IO gate"
                )


def test_search_with_reranker_path(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """Reranker pipeline plumbs end-to-end and preserves bounded IO."""
    from orbitbrief_core.retrieval import IdentityReranker

    if not mixed_envelope["packets"]:
        pytest.skip("no packets in envelope")
    idx = PacketIndex(retrieval_store, hash_embedder)
    idx.build(loaded_runtime)
    hits = idx.search(
        "scope",
        runtime=loaded_runtime,
        top_k=3,
        reranker=IdentityReranker(),
    )
    assert hits
    # IdentityReranker: scores descend N..1
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    # vector_score from the original cosine run is preserved in metadata.
    for h in hits:
        assert "vector_score" in h.metadata


def test_rebuild_replaces_existing_rows(
    loaded_runtime: EvidenceRuntime,
    retrieval_store: RetrievalStore,
    hash_embedder: DeterministicHashEmbedder,
    mixed_envelope: dict,
) -> None:
    """Rebuilding the same index doesn't double the row count."""
    idx = EvidenceIndex(retrieval_store, hash_embedder)
    n1 = idx.build(loaded_runtime)
    n2 = idx.build(loaded_runtime)
    assert n1 == n2 == len(mixed_envelope["atoms"])
    key = loaded_runtime.default_key
    assert key is not None
    assert (
        retrieval_store.count(
            INDEX_KIND_EVIDENCE,
            project_id=key.project_id,
            compile_id=key.compile_id,
        )
        == n1
    )


def test_dim_mismatch_between_embedder_and_store_is_rejected() -> None:
    """Wrong dim on either side fails loud at index construction."""
    from orbitbrief_core.retrieval import RetrievalStoreConfig

    store = RetrievalStore.connect(RetrievalStoreConfig(dim=64))
    bad_embedder = DeterministicHashEmbedder(dim=128)
    with pytest.raises(ValueError, match="dim"):
        EvidenceIndex(store, bad_embedder)
    store.close()
