"""Domain brains — per-vertical synthesizers over BriefState + retrieval.

A brain is a small, opinionated module that turns the planner's
:class:`BriefState` plus a typed :class:`RetrievalBundle` into a
domain-specific output schema (scope items, exclusions,
milestones, …). One brain per OrbitBrief domain pack.

Architectural rules (enforced by import-linter):

* Brains MUST NOT import :mod:`orbitbrief_core.evidence_runtime`
  or :mod:`orbitbrief_core.seam`. They never touch envelopes,
  raw files, or DuckDB. Anything they need flows through
  :class:`BriefState` and :class:`RetrievalBundle`.
* Brains MUST NOT import :mod:`orbitbrief_core.retrieval`. The
  orchestrator pre-bundles whatever a brain needs.
* Brains may import :mod:`orbitbrief_core.world_model.planner`
  (to depend on the :class:`BriefState` schema) and
  :mod:`orbitbrief_core.inference` (the chat client).

The first concrete brain is :mod:`orbitbrief_core.brains.managed_services`.
"""
from __future__ import annotations

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)

__all__ = ["PacketSnippet", "RetrievalBundle"]
