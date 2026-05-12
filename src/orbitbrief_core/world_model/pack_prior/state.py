"""Output schema for :class:`PackPrior`."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PackScore(BaseModel):
    """One pack's score summary in a :class:`PackPriorState`."""

    model_config = ConfigDict(frozen=True)

    pack_id: str
    display_name: str
    raw_score: int = Field(ge=0)  # token-hit count (no decay, integer)
    confidence: float = Field(ge=0.0, le=1.0)  # softmax-normalized
    matched_keywords: tuple[str, ...] = ()


class PackPriorState(BaseModel):
    """Deterministic JSON state emitted by :meth:`PackPrior.compute`.

    Reviewers can diff two states to see why a project routed to a
    different pack between runs.
    """

    model_config = ConfigDict(frozen=True)

    project_id: str
    compile_id: str
    # All packs, score-sorted desc, ties broken by pack_id for stability.
    scores: tuple[PackScore, ...]
    top_pack_id: str
    top_confidence: float = Field(ge=0.0, le=1.0)
    runner_up_pack_id: str | None = None
    runner_up_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    margin: float = Field(default=0.0, ge=0.0, le=1.0)
    # If we escalated to an LLM, the unescalated keyword winner. None
    # means the keyword pick stuck.
    escalated: bool = False
    pre_escalation_top_pack_id: str | None = None
    escalation_log: dict[str, Any] = Field(default_factory=dict)
    # Total atom-text tokens scored — useful for sanity checks
    # ("did we score zero tokens because the envelope is empty?").
    tokens_considered: int = Field(default=0, ge=0)
