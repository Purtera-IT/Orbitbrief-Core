"""Verdict thresholds + escalation reasons."""
from __future__ import annotations

from orbitbrief_core.calibrator.verdict import (
    EscalationReason,
    Verdict,
    decide_verdict,
)
from orbitbrief_core.validator.report import (
    ItemRef,
    ItemValidation,
    ValidationFailure,
    ValidationRuleId,
    ValidationSeverity,
)


def _ref(item_id: str = "x") -> ItemRef:
    return ItemRef(
        project_id="p", compile_id="c", brain="managed_services",
        section="scope_items", item_id=item_id,
    )


def _validation_with(severity: ValidationSeverity) -> ItemValidation:
    return ItemValidation(
        item=_ref(),
        failures=(
            ValidationFailure(
                rule_id=ValidationRuleId.PATH_LEGALITY,
                severity=severity,
                message="x",
            ),
        ),
    )


def test_blocker_always_rejects() -> None:
    verdict, reasons = decide_verdict(
        calibrated_prob=0.99,
        item_validation=_validation_with(ValidationSeverity.BLOCKER),
    )
    assert verdict is Verdict.REJECT
    assert EscalationReason.BLOCKER_VALIDATION_FAILURE in reasons


def test_high_prob_no_validator_issue_auto_accepts() -> None:
    verdict, reasons = decide_verdict(
        calibrated_prob=0.9, item_validation=None
    )
    assert verdict is Verdict.AUTO_ACCEPT
    assert EscalationReason.AUTO_OK in reasons


def test_borderline_prob_routes_to_review() -> None:
    verdict, reasons = decide_verdict(
        calibrated_prob=0.7, item_validation=None
    )
    assert verdict is Verdict.NEEDS_REVIEW
    assert EscalationReason.BORDERLINE_CONFIDENCE in reasons


def test_warning_with_high_prob_routes_to_review() -> None:
    verdict, reasons = decide_verdict(
        calibrated_prob=0.9,
        item_validation=_validation_with(ValidationSeverity.WARNING),
    )
    assert verdict is Verdict.NEEDS_REVIEW
    assert EscalationReason.WARNING_VALIDATION_FAILURE in reasons


def test_very_low_prob_rejects() -> None:
    verdict, reasons = decide_verdict(calibrated_prob=0.05, item_validation=None)
    assert verdict is Verdict.REJECT
    assert EscalationReason.LOW_CALIBRATED_CONFIDENCE in reasons
