"""Phase-4 refiner: deterministic graph-consistency pass over :class:`BriefState`.

Runs *after* :class:`Planner` and *before* downstream consumers.
The LLM can hallucinate (atom ids that don't exist, pack ids that
aren't in the registry, claims with sub-threshold confidence) —
this pass catches all of that without round-tripping the LLM
again.

Pipeline:

1. Drop claims whose atom ids don't resolve in the runtime
   (``unknown_atom``).
2. Drop claims whose pack id isn't in the active set
   (``unknown_pack``).
3. Drop pack activations whose pack id isn't in the registry.
4. Drop sites whose cluster id isn't in the SiteRealityState.
5. Deduplicate claims by ``(statement, sorted(supporting_atom_ids))``.
6. Add an INFO :class:`ReviewFlag` for each thing dropped so
   reviewers see the cleanup that happened.
7. Re-emit a new :class:`BriefState` (frozen models — refining is
   an out-of-place operation).
"""
from __future__ import annotations

from orbitbrief_core.world_model.refiner.refiner import (
    RefinementResult,
    refine_brief,
)

__all__ = ["RefinementResult", "refine_brief"]
