"""Verdict mapping: calibrated probability + validator → action."""
from __future__ import annotations

from enum import Enum

from orbitbrief_core.validator.report import ItemValidation


class Verdict(str, Enum):
    AUTO_ACCEPT = "auto_accept"
    NEEDS_REVIEW = "needs_review"
    REJECT = "reject"


class EscalationReason(str, Enum):
    """Why the calibrator routed an item to review or rejected it."""

    BLOCKER_VALIDATION_FAILURE = "blocker_validation_failure"
    LOW_CALIBRATED_CONFIDENCE = "low_calibrated_confidence"
    BORDERLINE_CONFIDENCE = "borderline_confidence"
    WARNING_VALIDATION_FAILURE = "warning_validation_failure"
    AMBIGUOUS_PACK_PRIOR = "ambiguous_pack_prior"
    HIGH_CONTRADICTION_DENSITY = "high_contradiction_density"
    AUTO_OK = "auto_ok"


def decide_verdict(
    *,
    calibrated_prob: float,
    item_validation: ItemValidation | None,
    auto_accept_threshold: float = 0.80,
    review_threshold: float = 0.55,
) -> tuple[Verdict, tuple[EscalationReason, ...]]:
    """Map (probability, validator) to (verdict, reasons).

    Three bands:

    * ``calibrated_prob ≥ auto_accept_threshold`` AND no blockers → auto_accept
    * ``review_threshold ≤ calibrated_prob < auto_accept_threshold`` →
      needs_review (always logs ``BORDERLINE_CONFIDENCE`` even when
      validator is clean — borderline confidence is its own reason)
    * Otherwise → needs_review at minimum, reject if calibrated_prob
      is < 0.20 or the validator flagged a blocker.
    """
    has_blocker = bool(item_validation and item_validation.has_blocker)
    has_warning = bool(
        item_validation and any(
            f.severity.value == "warning" for f in item_validation.failures
        )
    )

    reasons: list[EscalationReason] = []
    if has_blocker:
        reasons.append(EscalationReason.BLOCKER_VALIDATION_FAILURE)
        return Verdict.REJECT, tuple(reasons)

    if calibrated_prob < 0.20:
        reasons.append(EscalationReason.LOW_CALIBRATED_CONFIDENCE)
        return Verdict.REJECT, tuple(reasons)

    if calibrated_prob >= auto_accept_threshold and not has_warning:
        reasons.append(EscalationReason.AUTO_OK)
        return Verdict.AUTO_ACCEPT, tuple(reasons)

    if has_warning:
        reasons.append(EscalationReason.WARNING_VALIDATION_FAILURE)
    if review_threshold <= calibrated_prob < auto_accept_threshold:
        reasons.append(EscalationReason.BORDERLINE_CONFIDENCE)
    elif calibrated_prob < review_threshold:
        reasons.append(EscalationReason.LOW_CALIBRATED_CONFIDENCE)

    return Verdict.NEEDS_REVIEW, tuple(reasons)
