"""Pydantic types for the review queue + training log."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orbitbrief_core.calibrator.verdict import EscalationReason, Verdict
from orbitbrief_core.validator.report import ItemRef


class DecisionAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"


class ReviewItemStatus(str, Enum):
    OPEN = "open"
    DECIDED = "decided"
    EXPIRED = "expired"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReviewItem(BaseModel):
    """A queued item awaiting reviewer attention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ItemRef
    verdict: Verdict
    reasons: tuple[EscalationReason, ...]
    raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any]
    enqueued_at: str = Field(default_factory=_now_iso)
    status: ReviewItemStatus = ReviewItemStatus.OPEN

    @property
    def composite_id(self) -> str:
        return self.ref.composite_id


class ReviewDecision(BaseModel):
    """A reviewer's verdict on a queued :class:`ReviewItem`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    composite_id: str = Field(min_length=1)
    action: DecisionAction
    decided_by: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=1000)
    edited_payload: dict[str, Any] | None = None
    decided_at: str = Field(default_factory=_now_iso)


class TrainingRecord(BaseModel):
    """A supervision signal: brain prediction + reviewer ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    composite_id: str
    brain: str
    section: str
    project_id: str
    compile_id: str
    # Original brain prediction.
    predicted_payload: dict[str, Any]
    predicted_calibrated_confidence: float
    predicted_raw_confidence: float
    predicted_verdict: Verdict
    # Reviewer ground truth.
    reviewer_action: DecisionAction
    reviewer_notes: str = ""
    edited_payload: dict[str, Any] | None = None
    decided_by: str
    decided_at: str
    # Convenience: the binary "should this have been auto-accepted?" label.
    accepted: bool = False
