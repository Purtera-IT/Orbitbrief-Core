"""Typed output schema for :class:`Planner` — the ``BriefState``.

Everything the planner produces flows through these models. The
LLM is constrained to emit JSON that validates against
:class:`BriefState`; anything else gets rejected at the boundary.

Design notes:

* All collections are tuples (frozen) once validated so two runs
  on the same envelope can be compared with ``==``.
* :class:`Claim` is the grounding unit. ``supporting_atom_ids``
  must be non-empty after the refiner pass — the grounding test
  enforces that every atom id resolves in the runtime.
* :class:`ContradictionSummary` mirrors evidence_runtime
  contradictions; the planner does not invent contradictions, it
  only annotates the ones the substrate already detected.
* Confidences live on :class:`Claim`, :class:`PackActivation`, and
  :class:`SiteSummary` so a downstream calibrator can re-rank.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ────────────────────────────── enums ──────────────────────────────────


class PackStatus(str, Enum):
    """Planner's verdict on whether a pack should run downstream."""

    ACTIVE = "active"  # run downstream brains for this pack
    INACTIVE = "inactive"  # explicitly out-of-scope for this engagement
    WATCH = "watch"  # weak signal; surface but don't run brains yet


class SiteRole(str, Enum):
    """Role a clustered site plays in the engagement."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    OUT_OF_SCOPE = "out_of_scope"


class ReviewFlagSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class ReviewFlagCategory(str, Enum):
    CONTRADICTION = "contradiction"
    MISSING_EVIDENCE = "missing_evidence"
    AMBIGUITY = "ambiguity"
    SCOPE_GAP = "scope_gap"
    AUTHORITY_CONFLICT = "authority_conflict"


# ────────────────────────────── parts ──────────────────────────────────


class PackActivation(BaseModel):
    """Per-pack activation decision the planner emits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_id: str = Field(min_length=1)
    status: PackStatus
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=400)


class SiteSummary(BaseModel):
    """Per-site role + dependencies the planner emits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1, max_length=240)
    role: SiteRole
    confidence: float = Field(ge=0.0, le=1.0)
    depends_on_cluster_ids: tuple[str, ...] = ()


class Claim(BaseModel):
    """A grounded planner assertion. Must trace to packets + atoms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1, max_length=500)
    supporting_atom_ids: tuple[str, ...]
    supporting_packet_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    pack_id: str | None = None

    @model_validator(mode="after")
    def _has_atom_grounding(self) -> "Claim":
        if len(self.supporting_atom_ids) == 0:
            raise ValueError(
                f"claim {self.id!r}: supporting_atom_ids must be non-empty"
            )
        return self


class ContradictionSummary(BaseModel):
    """Pass-through of an evidence_runtime contradiction with planner annotation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: str
    from_atom_id: str
    to_atom_id: str
    entity_key: str | None = None
    severity: ReviewFlagSeverity
    summary: str = Field(min_length=1, max_length=400)


class ReviewFlag(BaseModel):
    """A reviewer-facing flag the planner raises."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ReviewFlagSeverity
    category: ReviewFlagCategory
    message: str = Field(min_length=1, max_length=400)
    related_atom_ids: tuple[str, ...] = ()


class OrchestrationDirective(BaseModel):
    """Instruction for the downstream orchestrator (composers, brains)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal[
        "run_brain",
        "request_review",
        "skip_pack",
        "request_clarification",
    ]
    target: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────── BriefState ─────────────────────────────


class BriefState(BaseModel):
    """The single artifact :class:`Planner` emits per envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    compile_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    pack_activations: tuple[PackActivation, ...]
    sites: tuple[SiteSummary, ...]
    claims: tuple[Claim, ...]
    contradictions: tuple[ContradictionSummary, ...] = ()
    review_flags: tuple[ReviewFlag, ...] = ()
    orchestration: tuple[OrchestrationDirective, ...] = ()
    # Provenance: which model wrote this and how much it cost.
    model_used: str = Field(min_length=1)
    tier: Literal["default", "escalated"] = "default"
    escalation_log: dict[str, Any] = Field(default_factory=dict)
    token_cost: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def json_schema_for_llm(cls) -> dict[str, Any]:
        """Schema given to the LLM as the JSON-mode constraint.

        We strip Pydantic-only metadata that some servers reject
        (``$defs`` cycles, custom validators) and pin object types
        with ``additionalProperties: false`` so the model can't
        sneak extra fields past validation.
        """
        return cls.model_json_schema(mode="serialization")
