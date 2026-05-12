"""Rerankers: re-score (query, doc[]) pairs against a richer model.

In production this is Qwen3-Reranker-8B; in tests we use
:class:`IdentityReranker` which preserves input order and returns
descending integer scores. This is enough to validate the
*pipeline shape* without a network round-trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from orbitbrief_core.inference.client import InferenceClient


class Reranker(Protocol):
    """Anything that can re-score (query, doc[]) pairs."""

    @property
    def model_id(self) -> str:
        ...

    def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[tuple[int, float]]:
        """Return ``[(orig_index, score), ...]`` sorted by score desc."""
        ...


@dataclass
class RemoteVllmReranker:
    """vLLM-backed reranker. Production target: Qwen3-Reranker-8B."""

    client: InferenceClient
    model_id: str

    def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[tuple[int, float]]:
        return self.client.rerank(
            query, documents, model=self.model_id, top_n=top_n
        )


@dataclass
class IdentityReranker:
    """Test stub: preserves input order, scores N..1.

    Useful for unit tests that want to verify the rerank call is
    *made* and its output is *consumed* without depending on a
    real model. Don't use in production — it does no actual
    reranking.
    """

    model_id: str = "identity-reranker-v1"

    def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[tuple[int, float]]:
        n = len(documents)
        scored = [(i, float(n - i)) for i in range(n)]
        if top_n is not None:
            scored = scored[:top_n]
        return scored
