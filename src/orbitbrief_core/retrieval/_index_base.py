"""Internal: shared build/search machinery for the four indices.

All four indices have the same shape: pull source rows from an
:class:`EvidenceRuntime`, project to ``(ref_id, text, metadata)``,
embed the texts, write into a vss table, search by re-embedding
the query. Differences are only in the projection.

Subclasses override :meth:`_iter_source_rows` and
:meth:`_metadata_for`. Everything else lives here so the four
public modules stay focused on their projection logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from orbitbrief_core.evidence_runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.retrieval.base import IndexKind, RetrievalHit
from orbitbrief_core.retrieval.embedder import Embedder
from orbitbrief_core.retrieval.reranker import Reranker
from orbitbrief_core.retrieval.store import RetrievalStore


@dataclass(frozen=True)
class _SourceRow:
    """One row to embed, before vectorization."""

    ref_id: str
    text: str
    metadata: dict


class _BaseIndex:
    """Shared build + search; subclasses contribute the projection."""

    KIND: IndexKind

    def __init__(
        self,
        store: RetrievalStore,
        embedder: Embedder,
    ) -> None:
        if embedder.dim != store.config.dim:
            raise ValueError(
                f"{type(self).__name__}: embedder.dim={embedder.dim} != "
                f"store.dim={store.config.dim}"
            )
        self._store = store
        self._embedder = embedder
        # Last-built key. Lets ``search`` work without a caller
        # passing ``key=`` or ``runtime=`` in the common single-
        # envelope build-then-search pattern.
        self._last_build_key: RuntimeKey | None = None

    @property
    def store(self) -> RetrievalStore:
        return self._store

    @property
    def last_build_key(self) -> RuntimeKey | None:
        return self._last_build_key

    # ───── build ─────

    def build(
        self,
        runtime: EvidenceRuntime,
        *,
        key: RuntimeKey | None = None,
        batch_size: int = 64,
        ensure_hnsw: bool = True,
    ) -> int:
        """Vectorize source rows and bulk-load them into the store.

        Returns the row count written. Re-running for the same key
        replaces existing rows (handy during development).
        """
        rk = self._resolve_key(runtime, key)
        rows = list(self._iter_source_rows(runtime, rk))
        if not rows:
            # Defensive: no rows is a legal but worth noting state
            # (e.g. a project with no claim atoms). Caller can check
            # the return value.
            return 0
        written = 0
        for batch in _chunked(rows, batch_size):
            vecs = self._embedder.embed([r.text for r in batch])
            triples = [
                (r.ref_id, r.metadata, vec)
                for r, vec in zip(batch, vecs)
            ]
            written += self._store.upsert(
                self.KIND,
                project_id=rk.project_id,
                compile_id=rk.compile_id,
                rows=triples,
            )
        if ensure_hnsw:
            # HNSW build is amortized over many searches; always
            # worth it after a real bulk load.
            self._store.ensure_hnsw(self.KIND)
        self._last_build_key = rk
        return written

    # ───── search ─────

    def search(
        self,
        query: str,
        *,
        runtime: EvidenceRuntime | None = None,
        key: RuntimeKey | None = None,
        top_k: int = 10,
        reranker: Reranker | None = None,
        rerank_pool: int | None = None,
    ) -> list[RetrievalHit]:
        """Find the top-``k`` rows similar to ``query``.

        With ``reranker`` set, we first pull the top
        ``rerank_pool`` (default ``3 * top_k``) by vector similarity,
        then re-score with the reranker — but **without** sending
        the doc text to the reranker (we have no text to send: this
        substrate doesn't store bodies). Pass a runtime so we can
        re-hydrate compact rows for the reranker call. If neither a
        runtime nor a reranker is given, results come back in pure
        cosine-similarity order with no rerank step.
        """
        if reranker is not None and runtime is None:
            raise ValueError(
                "search(reranker=...) requires runtime= so we can "
                "re-hydrate row bodies for the reranker"
            )
        rk = self._resolve_search_key(runtime, key)
        qvec = self._embedder.embed([query])[0]
        pool = (rerank_pool or top_k * 3) if reranker is not None else top_k
        raw = self._store.search(
            self.KIND,
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            query_vec=qvec,
            top_k=pool,
        )
        hits = [
            RetrievalHit(id=ref_id, score=score, kind=self.KIND, metadata=meta)
            for ref_id, score, meta in raw
        ]
        if reranker is None or not hits:
            return hits[:top_k]
        # Re-hydrate texts ONLY for the rerank call. We do not put
        # them into the returned hits.
        assert runtime is not None
        bodies = [self._hydrate_text(runtime, h, rk) for h in hits]
        ranked = reranker.rerank(query, bodies, top_n=top_k)
        out: list[RetrievalHit] = []
        for orig_idx, score in ranked:
            base = hits[orig_idx]
            out.append(
                RetrievalHit(
                    id=base.id,
                    score=score,
                    kind=base.kind,
                    metadata={**base.metadata, "vector_score": base.score},
                )
            )
        return out

    # ───── overrides ─────

    def _iter_source_rows(
        self, runtime: EvidenceRuntime, key: RuntimeKey
    ) -> Iterator[_SourceRow]:
        raise NotImplementedError

    def _hydrate_text(
        self, runtime: EvidenceRuntime, hit: RetrievalHit, key: RuntimeKey
    ) -> str:
        """Subclasses look up the body for one hit (rerank-only path)."""
        raise NotImplementedError

    # ───── helpers ─────

    def _resolve_key(
        self, runtime: EvidenceRuntime, key: RuntimeKey | None
    ) -> RuntimeKey:
        rk = key or runtime.default_key
        if rk is None:
            raise ValueError("no RuntimeKey available; pass key= or load an envelope")
        return rk

    def _resolve_search_key(
        self, runtime: EvidenceRuntime | None, key: RuntimeKey | None
    ) -> RuntimeKey:
        if key is not None:
            return key
        if runtime is not None and runtime.default_key is not None:
            return runtime.default_key
        # Common build-then-search pattern: index remembers the
        # last key it built for and reuses it. If the index was
        # never built this session, this falls through to error.
        if self._last_build_key is not None:
            return self._last_build_key
        raise ValueError(
            "search needs a RuntimeKey: pass key=, pass runtime= with a "
            "default, or call build() on this index first"
        )


def _chunked(seq: list, size: int) -> Iterable[list]:
    """Yield ``size``-sized chunks of ``seq`` (last chunk may be smaller)."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
