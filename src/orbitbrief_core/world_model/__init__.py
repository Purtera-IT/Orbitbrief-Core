"""Phase 3 — World model: deterministic engines with light neural assist.

Two engines today:

* :class:`PackPrior` (``world_model.pack_prior``) — picks the most
  likely OrbitBrief domain pack(s) for a project from the
  envelope's atom text. Pure keyword scoring against the
  intake-workbook-derived registry; an LLM is consulted **only**
  when the top-2 packs are within 0.15 confidence.
* :class:`SiteRealityEngine` (``world_model.site_reality``) — walks
  the entity + edge graph to cluster atoms by ``site:*`` keys.
  An LLM is consulted **only** when a cluster has multiple
  competing canonical names.

Both engines log every escalation with a structured
:class:`EscalationReason` so the corpus-wide LLM-call rate is
auditable. The Phase-3 spec caps that rate at < 20 % of cases.
"""
from __future__ import annotations

from orbitbrief_core.world_model.escalation import (
    Escalation,
    EscalationLog,
    EscalationReason,
)
from orbitbrief_core.world_model.pack_prior import (
    PackPrior,
    PackPriorState,
    PackScore,
)
from orbitbrief_core.world_model.planner import (
    BriefState,
    Claim,
    OrchestrationDirective,
    PackActivation,
    Planner,
    PlannerEscalation,
    PlannerEscalationReason,
    PlannerInputs,
    PlannerPrompt,
    PlannerResult,
    PlannerTier,
    ReviewFlag,
    SiteSummary,
)
from orbitbrief_core.world_model.refiner import RefinementResult, refine_brief
from orbitbrief_core.world_model.registry import (
    DomainPack,
    DomainPackRegistry,
    load_default_registry,
)
from orbitbrief_core.world_model.site_reality import (
    SiteCluster,
    SiteRealityEngine,
    SiteRealityState,
)

__all__ = [
    "BriefState",
    "Claim",
    "DomainPack",
    "DomainPackRegistry",
    "Escalation",
    "EscalationLog",
    "EscalationReason",
    "OrchestrationDirective",
    "PackActivation",
    "PackPrior",
    "PackPriorState",
    "PackScore",
    "Planner",
    "PlannerEscalation",
    "PlannerEscalationReason",
    "PlannerInputs",
    "PlannerPrompt",
    "PlannerResult",
    "PlannerTier",
    "RefinementResult",
    "ReviewFlag",
    "SiteCluster",
    "SiteRealityEngine",
    "SiteRealityState",
    "SiteSummary",
    "load_default_registry",
    "refine_brief",
]
