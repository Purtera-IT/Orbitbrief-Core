"""Inference clients (Phase 2 minimum, expanded in later phases).

Today: HTTP clients for an OpenAI-compatible vLLM server providing
``/v1/embeddings`` and ``/v1/rerank`` endpoints (Qwen3-Embedding-8B
and Qwen3-Reranker-8B in production).

Tomorrow (Phase 3+): chat / completion / structured-decoding clients
for the world-synthesis and brain stacks.

This package is the **only** place outbound model traffic happens.
Retrieval, brains, composers all funnel through here so we have a
single chokepoint for retries, rate-limiting, telemetry, and (later)
swapping inference providers.
"""
from __future__ import annotations

from orbitbrief_core.inference.client import (
    InferenceClient,
    InferenceError,
    NullInferenceClient,
    VllmInferenceClient,
)

__all__ = [
    "InferenceClient",
    "InferenceError",
    "NullInferenceClient",
    "VllmInferenceClient",
]
