"""Phase-7 orchestrator: end-to-end ``envelope.json → reviewable brief``.

This is the **only** module in OrbitBrief Core that may legitimately
import across all six layers (substrate, retrieval, world_model,
brains, validator, calibrator, review_runtime). Every other layer
stays in its own lane — the orchestrator is the integrator.

Public surface:

* :class:`BriefPipeline` — orchestrates the six phases against one
  envelope. Returns a :class:`BriefArtifacts` handle pointing at every
  intermediate artifact.
* :class:`BrainRegistry` — pack-id → brain-factory map. The default
  registry (:func:`default_brain_registry`) currently maps
  ``msp`` → :class:`ManagedServicesBrain` and is the seam for adding
  more brains.
* :class:`BundleAssembler` — wraps an :class:`EvidenceRuntime` to
  produce typed :class:`RetrievalBundle` instances per active pack.

CLI:

    python -m orbitbrief_core.orchestrator compile envelope.json --out artifacts/

Or via the convenience script at the repo root:

    python compile_brief.py engagement.json --out artifacts/
"""
from __future__ import annotations

from orbitbrief_core.orchestrator.artifacts import (
    BriefArtifacts,
    StageStatus,
    StageRecord,
)
from orbitbrief_core.orchestrator.brain_registry import (
    BrainFactory,
    BrainRegistry,
    default_brain_registry,
)
from orbitbrief_core.orchestrator.bundle_assembler import BundleAssembler
from orbitbrief_core.orchestrator.pipeline import (
    BriefPipeline,
    PipelineConfig,
    PipelineResult,
)

__all__ = [
    "BrainFactory",
    "BrainRegistry",
    "BriefArtifacts",
    "BriefPipeline",
    "BundleAssembler",
    "PipelineConfig",
    "PipelineResult",
    "StageRecord",
    "StageStatus",
    "default_brain_registry",
]
