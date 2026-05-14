"""Phase-6 validator: deterministic trust layer over brain outputs.

Inputs:

* The brain's output state (today: :class:`ManagedServicesScopeState`
  — generalizes to any brain that subclasses the same shape).
* The :class:`RetrievalBundle` the brain consumed.
* The planner's :class:`BriefState` (for site / pack consistency).
* Optionally an :class:`EvidenceLookup` — a typed protocol that
  resolves ``atom_id → atom dict`` so we can enforce *path
  legality* (claim → packet → atom → ``source_ref``). The
  evidence_runtime adapter implements this protocol; the
  orchestrator wires it.

The validator returns a :class:`ValidationReport` with two lists:
``passed_items`` and ``failed_items``. Failed items carry the
specific :class:`ValidationRuleId` that fired plus a structured
``detail`` dict reviewers can act on. The validator does **not**
mutate the brain output — that's the calibrator's job (it can
demote items based on the report).
"""
from __future__ import annotations

from orbitbrief_core.validator.evidence_lookup import (
    DictEvidenceLookup,
    EvidenceLookup,
    NullEvidenceLookup,
    RuntimeEvidenceLookup,
)
from orbitbrief_core.validator.report import (
    ItemRef,
    ItemValidation,
    ValidationFailure,
    ValidationReport,
    ValidationRuleId,
    ValidationSeverity,
)
from orbitbrief_core.validator.validator import (
    BrainOutputValidator,
    PackIncompatibility,
)

from orbitbrief_core.validator.sow_completeness import (
    SowCompletenessFinding,
    SowCompletenessResult,
    evaluate_from_case_payloads,
    evaluate_sow_completeness,
    load_sow_rules,
)

__all__ = [
    "BrainOutputValidator",
    "DictEvidenceLookup",
    "EvidenceLookup",
    "ItemRef",
    "ItemValidation",
    "NullEvidenceLookup",
    "PackIncompatibility",
    "RuntimeEvidenceLookup",
    "ValidationFailure",
    "ValidationReport",
    "ValidationRuleId",
    "ValidationSeverity",
    "SowCompletenessFinding",
    "SowCompletenessResult",
    "evaluate_from_case_payloads",
    "evaluate_sow_completeness",
    "load_sow_rules",
]
