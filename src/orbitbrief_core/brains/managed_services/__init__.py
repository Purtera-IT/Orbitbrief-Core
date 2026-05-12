"""Managed Services brain — first OrbitBrief domain brain.

Cold-start version: Qwen3-14B + structured prompt + bounded JSON
output. A LoRA-fine-tuned variant lands later; the wire format
won't change.

Inputs (typed, no envelope/raw access):

* :class:`BriefState` — what the planner decided about this engagement.
* :class:`RetrievalBundle` — relevant packets the orchestrator
  pre-bundled (scope_inclusion, scope_exclusion, missing_info, …).

Output: :class:`ManagedServicesScopeState` — seven sections
(scope items, exclusions, customer responsibilities, milestones,
assumptions, dispatch readiness flags, open questions). Every
item carries packet/atom grounding.

The brain enforces:

* JSON output only (``response_format={"type": "json_object"}``).
* All grounding ids resolve in the supplied :class:`RetrievalBundle`
  (post-call validator pass).
* Hard fall-back to a deterministic skeleton on validation failure
  (BLOCKER review flag in the state).
"""
from __future__ import annotations

from orbitbrief_core.brains.managed_services.runner import (
    ManagedServicesBrain,
    ManagedServicesBrainResult,
)
from orbitbrief_core.brains.managed_services.schema import (
    Assumption,
    CustomerResponsibility,
    DispatchReadinessFlag,
    Exclusion,
    ManagedServicesScopeState,
    Milestone,
    OpenQuestion,
    ReadinessSeverity,
    ScopeItem,
)

__all__ = [
    "Assumption",
    "CustomerResponsibility",
    "DispatchReadinessFlag",
    "Exclusion",
    "ManagedServicesBrain",
    "ManagedServicesBrainResult",
    "ManagedServicesScopeState",
    "Milestone",
    "OpenQuestion",
    "ReadinessSeverity",
    "ScopeItem",
]
