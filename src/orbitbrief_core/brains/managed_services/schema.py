"""Output schema for :class:`ManagedServicesBrain`.

Seven sections (matching the Phase-5 spec): scope items,
exclusions, customer responsibilities, milestones, assumptions,
dispatch readiness flags, open questions. Every item that comes
from a brain claim carries packet- and atom-level grounding so
the validator and reviewer UIs can trace back to source.

All collections are tuples (frozen). The brain can only emit
fields declared here — Pydantic's ``extra="forbid"`` rejects
anything new.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ────────────────────────────── enums ──────────────────────────────────


class ReadinessSeverity(str, Enum):
    """Severity for a single dispatch-readiness flag."""

    GREEN = "green"  # ready to dispatch
    YELLOW = "yellow"  # ready, but with caveat the PM should know
    RED = "red"  # not ready; blocker before dispatch


class MilestoneStatus(str, Enum):
    PROPOSED = "proposed"
    SCHEDULED = "scheduled"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"


# ────────────────────────────── parts ──────────────────────────────────


class _Grounded(BaseModel):
    """Mixin shape — every brain-emitted item must cite at least one packet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1, max_length=500)
    supporting_packet_ids: tuple[str, ...]
    supporting_atom_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _has_packet_grounding(self) -> "_Grounded":
        if len(self.supporting_packet_ids) == 0:
            raise ValueError(
                f"item {self.id!r}: supporting_packet_ids must be non-empty"
            )
        return self


class ScopeItem(_Grounded):
    """One thing the engagement WILL deliver."""

    category: str = Field(default="general", max_length=80)


class Exclusion(_Grounded):
    """One thing the engagement explicitly will NOT deliver."""

    rationale: str = Field(default="", max_length=400)


class CustomerResponsibility(_Grounded):
    """Action the customer must take for the work to proceed."""

    deadline_relative: str = Field(default="", max_length=120)


class Milestone(_Grounded):
    """A schedule-affecting checkpoint."""

    status: MilestoneStatus = MilestoneStatus.PROPOSED
    target_relative: str = Field(default="", max_length=120)


class Assumption(_Grounded):
    """A documented assumption the engagement is built on."""

    risk_if_false: str = Field(default="", max_length=400)


class DispatchReadinessFlag(_Grounded):
    """A go/no-go indicator the dispatch team consults before scheduling."""

    severity: ReadinessSeverity
    blocker_owner: str = Field(default="", max_length=120)


class OpenQuestion(_Grounded):
    """A question that must be answered before brief sign-off."""

    addressee: str = Field(default="customer", max_length=120)


# ────────────────────────────── state ──────────────────────────────────


class ManagedServicesScopeState(BaseModel):
    """The structured output of :class:`ManagedServicesBrain`.

    Provenance fields (``model_used``, ``token_cost``,
    ``fallback_used``, ``unresolved_ids``) are stamped by the
    runner — the LLM is told to leave them unset.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    compile_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)

    scope_items: tuple[ScopeItem, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    customer_responsibilities: tuple[CustomerResponsibility, ...] = ()
    milestones: tuple[Milestone, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    dispatch_readiness_flags: tuple[DispatchReadinessFlag, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()

    # Provenance.
    model_used: str = Field(default="", max_length=80)
    token_cost: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False
    # Validator output: ids the LLM cited but the bundle didn't
    # contain. Empty when the brain ran cleanly.
    unresolved_packet_ids: tuple[str, ...] = ()
    unresolved_atom_ids: tuple[str, ...] = ()
