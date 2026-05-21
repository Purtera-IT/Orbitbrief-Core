"""Embedding-head fine-tune — SCAFFOLDED, NOT CONNECTED.

Triplet-loss fine-tune of a small projection head on top of the
frozen ``qwen3-embedding:8b`` base. When active, replaces the
zero-shot embedder used by all 4 retrieval indices + the packet
``semantic_link`` edges.

Why head-only? Fine-tuning the full 8B base costs GPU + risks
regressing zero-shot generalization. A projection head (~3M params)
on top of frozen embeddings gives 80% of the benefit at 1% of the
cost.

See ``README.md`` for activation path. ``IS_ACTIVE`` flag below.
"""
from __future__ import annotations

__all__ = ["IS_ACTIVE"]

IS_ACTIVE: bool = False
