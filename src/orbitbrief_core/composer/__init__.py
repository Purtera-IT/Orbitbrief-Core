"""Phase-8 composer: aggregate brain outputs into a single :class:`ComposedBrief`.

A :class:`ComposedBrief` is the document a PM actually reads.
The composer takes:

* The planner's :class:`BriefState` (Phase 4) — for engagement-level
  context (sites, contradictions, escalation log, model used).
* Per-pack :class:`BriefingState` (Phase 7.5) and / or
  :class:`ManagedServicesScopeState` (Phase 5) outputs.
* Per-pack :class:`CalibratorReport` (Phase 6) — so each item in
  the doc carries its calibrated confidence + verdict + reasons.
* Per-pack :class:`ValidationReport` (Phase 6) — drives the
  flag/warning surface in the doc.

It produces:

* A typed :class:`ComposedBrief` (Pydantic, frozen) for downstream
  programmatic use.
* A Markdown render via :func:`render_markdown` (used by the
  Phase-8 reviewer UI and any other downstream document pipeline).

The composer never calls an LLM. It's a deterministic
:func:`brain_outputs → reviewable doc` pass — so identical inputs
produce identical docs (good for diffing across runs).

Architectural rules:
* The composer may import :class:`BriefingState`,
  :class:`ManagedServicesScopeState`,
  :class:`CalibratorReport`, :class:`ValidationReport`,
  :class:`BriefState`. It must NOT import the runtime, retrieval,
  or any brain runner.
"""
from __future__ import annotations

from orbitbrief_core.composer.composer import (
    ComposedBrief,
    Composer,
    ComposerConfig,
    ComposerInputs,
    DomainSection,
    DomainSectionItem,
    ExecutiveSummary,
    SiteRosterEntry,
)
from orbitbrief_core.composer.markdown import render_markdown

__all__ = [
    "ComposedBrief",
    "Composer",
    "ComposerConfig",
    "ComposerInputs",
    "DomainSection",
    "DomainSectionItem",
    "ExecutiveSummary",
    "SiteRosterEntry",
    "render_markdown",
]
