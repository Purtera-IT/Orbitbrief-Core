"""Phase-4 planner: synthesizes a typed :class:`BriefState` from runtime inputs.

The planner is the *only* world-model component that writes free-
form prose (claims, rationales, review-flag messages). Everything
else stays deterministic. This is also the only component that
calls a chat LLM by default — pack_prior and site_reality (Phase
3) escalate sparingly; the planner runs every time.

Composition:

* :class:`BriefState` and friends — the typed output (``schema.py``).
* :class:`PlannerPrompt` — assembles the system + user messages from
  PackPriorState, SiteRealityState, retrieval bundles, and
  contradictions (``prompt.py``).
* :class:`Planner` — orchestrates: assemble inputs → call LLM with
  guided JSON → validate → fall back to deterministic skeleton on
  hard failure (``runner.py``).
* :class:`PlannerEscalation` — pre-call rule that picks 14B vs 32B
  with a structured reason (``escalation.py``).

The :func:`refine_brief` pass (``world_model.refiner``) runs
*after* the planner and enforces graph-consistency invariants.
"""
from __future__ import annotations

from orbitbrief_core.world_model.planner.escalation import (
    PlannerEscalation,
    PlannerEscalationReason,
    PlannerTier,
)
from orbitbrief_core.world_model.planner.prompt import PlannerInputs, PlannerPrompt
from orbitbrief_core.world_model.planner.runner import Planner, PlannerResult
from orbitbrief_core.world_model.planner.schema import (
    BriefState,
    Claim,
    ContradictionSummary,
    OrchestrationDirective,
    PackActivation,
    ReviewFlag,
    ReviewFlagCategory,
    ReviewFlagSeverity,
    SiteSummary,
)

__all__ = [
    "BriefState",
    "Claim",
    "ContradictionSummary",
    "OrchestrationDirective",
    "PackActivation",
    "Planner",
    "PlannerEscalation",
    "PlannerEscalationReason",
    "PlannerInputs",
    "PlannerPrompt",
    "PlannerResult",
    "PlannerTier",
    "ReviewFlag",
    "ReviewFlagCategory",
    "ReviewFlagSeverity",
    "SiteSummary",
]
