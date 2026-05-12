"""Embedders: text → fixed-dim float vector.

Two implementations:

* :class:`RemoteVllmEmbedder` — wraps an :class:`InferenceClient`
  pointed at a vLLM serving Qwen3-Embedding-8B (4096 dim) in
  production. Cached on ``(text, model)`` to avoid re-embedding the
  same body across the four indices.
* :class:`DeterministicHashEmbedder` — pure-Python lexical n-gram
  embedder used by tests and CI. Reproducible across runs and
  machines, free of network dependencies, **good enough** for
  recall@10 ≥ 0.8 on a designed golden set (because docs sharing
  tokens with the query land in the same hash buckets). Not a
  replacement for a real embedder — it has zero semantic
  understanding.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from orbitbrief_core.inference.client import InferenceClient


class Embedder(Protocol):
    """Anything that can turn texts into fixed-dim vectors."""

    @property
    def dim(self) -> int:
        ...

    @property
    def model_id(self) -> str:
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


# ────────────────────────────── remote (vLLM) ─────────────────────────


@dataclass
class RemoteVllmEmbedder:
    """vLLM-backed embedder.

    Production target is Qwen3-Embedding-8B (4096 dim). ``dim`` must
    match what the server actually returns; we don't probe at
    construction because that would require a network round-trip.
    """

    client: InferenceClient
    model_id: str  # e.g. "Qwen/Qwen3-Embedding-8B"
    dim: int  # vector dimension; must match server output
    _cache: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts``, caching on text identity to skip duplicates."""
        if not texts:
            return []
        # Resolve cached vs uncached, preserving caller order so the
        # output positionally matches ``texts``.
        result: list[list[float] | None] = [None] * len(texts)
        to_fetch: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            cached = self._cache.get(t)
            if cached is not None:
                result[i] = cached
            else:
                to_fetch.append((i, t))
        if to_fetch:
            fresh = self.client.embed([t for _, t in to_fetch], model=self.model_id)
            if len(fresh) != len(to_fetch):
                raise RuntimeError(
                    f"embed: server returned {len(fresh)} vectors for "
                    f"{len(to_fetch)} inputs"
                )
            for (i, t), vec in zip(to_fetch, fresh):
                if len(vec) != self.dim:
                    raise RuntimeError(
                        f"embed: server returned dim={len(vec)} but client "
                        f"expects dim={self.dim}"
                    )
                self._cache[t] = vec
                result[i] = vec
        # mypy: every slot is now filled
        return [v for v in result if v is not None]


# ────────────────────────────── deterministic stub ────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class DeterministicHashEmbedder:
    """Lexical-n-gram hash embedder. Deterministic, network-free, dim-configurable.

    Process: lowercase → token + char-trigram split → SHA-256 the
    feature → modulo into ``dim`` slots → tf weight → L2-normalize.

    Because docs sharing tokens with a query map to the same
    buckets, cosine similarity tracks lexical overlap — enough to
    drive a recall@10 smoke test on a designed golden set, while
    being completely deterministic across runs and machines.

    Use this in tests, never in production.
    """

    dim: int = 128
    model_id: str = "deterministic-hash-v1"
    n_min: int = 3  # min char n-gram size
    n_max: int = 4  # max char n-gram size

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feature in self._features(text):
            slot = self._slot(feature)
            sign = 1.0 if (self._slot(feature + "$sign") & 1) == 0 else -1.0
            vec[slot] += sign
        # L2 normalize so cosine similarity = dot product.
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def _slot(self, feature: str) -> int:
        h = hashlib.sha256(feature.encode("utf-8")).digest()
        # First 4 bytes → unsigned int → mod dim.
        return int.from_bytes(h[:4], "big") % self.dim

    def _features(self, text: str) -> list[str]:
        text = text.lower()
        feats: list[str] = []
        # Word tokens
        for tok in _TOKEN_RE.findall(text):
            feats.append("w:" + tok)
        # Character n-grams over the whole string (with sentinel
        # boundaries so prefix/suffix matter).
        padded = "^" + text + "$"
        for n in range(self.n_min, self.n_max + 1):
            for i in range(0, max(1, len(padded) - n + 1)):
                feats.append(f"c{n}:" + padded[i : i + n])
        return feats
