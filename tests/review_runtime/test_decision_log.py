"""Phase-6 verify gate: every accept/reject/edit emits a TrainingRecord."""
from __future__ import annotations

from pathlib import Path

import pytest

from orbitbrief_core.calibrator.calibrator import CalibratedItem
from orbitbrief_core.calibrator.verdict import EscalationReason, Verdict
from orbitbrief_core.review_runtime import (
    DecisionAction,
    InMemoryReviewQueue,
    InMemoryTrainingLog,
    JsonlReviewQueue,
    JsonlTrainingLog,
    ReviewDecision,
    ReviewItemStatus,
    record_decision,
)
from orbitbrief_core.validator.report import ItemRef


def _calibrated_item(
    item_id: str = "s1",
    *,
    verdict: Verdict = Verdict.NEEDS_REVIEW,
    calibrated: float = 0.65,
) -> CalibratedItem:
    return CalibratedItem(
        ref=ItemRef(
            project_id="p1",
            compile_id="c1",
            brain="managed_services",
            section="scope_items",
            item_id=item_id,
        ),
        raw_confidence=0.7,
        calibrated_confidence=calibrated,
        verdict=verdict,
        reasons=(EscalationReason.BORDERLINE_CONFIDENCE,),
        signals={"parser_confidence": 0.8},
        payload={"id": item_id, "statement": "demo", "category": "general"},
    )


def _decision(item_id: str, *, action: DecisionAction, by: str = "pm@x.com") -> ReviewDecision:
    return ReviewDecision(
        composite_id=f"p1/c1/managed_services/scope_items/{item_id}",
        action=action,
        decided_by=by,
        notes="reviewed",
    )


def test_every_decision_emits_training_record() -> None:
    """One review decision → one training record with predicted + reviewer fields."""
    queue = InMemoryReviewQueue()
    log = InMemoryTrainingLog()

    enqueued = queue.enqueue(_calibrated_item("s1"))
    decision = _decision("s1", action=DecisionAction.ACCEPT)
    queue.record_decision(decision)
    record = record_decision(item=enqueued, decision=decision, log=log)

    assert len(log.all()) == 1
    assert record.composite_id == enqueued.composite_id
    assert record.predicted_calibrated_confidence == 0.65
    assert record.predicted_verdict is Verdict.NEEDS_REVIEW
    assert record.reviewer_action is DecisionAction.ACCEPT
    assert record.accepted is True


def test_three_actions_each_log_a_record() -> None:
    """Accept, reject, and edit all surface as TrainingRecords with the right ``accepted`` flag."""
    queue = InMemoryReviewQueue()
    log = InMemoryTrainingLog()

    items = [queue.enqueue(_calibrated_item(f"s{i}")) for i in range(3)]
    actions = [DecisionAction.ACCEPT, DecisionAction.REJECT, DecisionAction.EDIT]
    edited_payloads = [None, None, {"id": "s2", "statement": "edited", "category": "patched"}]

    for item, action, edited in zip(items, actions, edited_payloads):
        decision = ReviewDecision(
            composite_id=item.composite_id,
            action=action,
            decided_by="pm@x.com",
            notes="r",
            edited_payload=edited,
        )
        queue.record_decision(decision)
        record_decision(item=item, decision=decision, log=log)

    records = log.all()
    assert len(records) == 3
    assert {r.reviewer_action for r in records} == set(actions)
    by_action = {r.reviewer_action: r for r in records}
    assert by_action[DecisionAction.ACCEPT].accepted is True
    assert by_action[DecisionAction.EDIT].accepted is True
    assert by_action[DecisionAction.REJECT].accepted is False
    assert by_action[DecisionAction.EDIT].edited_payload == edited_payloads[2]


def test_decision_status_marks_item_decided() -> None:
    queue = InMemoryReviewQueue()
    enqueued = queue.enqueue(_calibrated_item("s1"))
    assert enqueued.status is ReviewItemStatus.OPEN

    decided = queue.record_decision(_decision("s1", action=DecisionAction.REJECT))
    assert decided.status is ReviewItemStatus.DECIDED
    assert queue.get(enqueued.composite_id).status is ReviewItemStatus.DECIDED
    # The open list no longer contains it.
    assert queue.list_open() == ()


def test_jsonl_queue_replays_after_restart(tmp_path: Path) -> None:
    """Persisted queue + log survive a process restart."""
    queue = JsonlReviewQueue(tmp_path)
    enqueued = queue.enqueue(_calibrated_item("s1"))
    queue.record_decision(_decision("s1", action=DecisionAction.ACCEPT))

    log = JsonlTrainingLog(tmp_path)
    record_decision(
        item=enqueued,
        decision=_decision("s1", action=DecisionAction.ACCEPT),
        log=log,
    )

    # Simulate restart: build new queue + log over the same dir.
    queue2 = JsonlReviewQueue(tmp_path)
    log2 = JsonlTrainingLog(tmp_path)
    assert queue2.get(enqueued.composite_id) is not None
    assert queue2.get(enqueued.composite_id).status is ReviewItemStatus.DECIDED
    assert len(log2.all()) == 1


def test_decision_for_unknown_item_raises() -> None:
    queue = InMemoryReviewQueue()
    with pytest.raises(KeyError):
        queue.record_decision(_decision("ghost", action=DecisionAction.ACCEPT))


def test_record_decision_rejects_id_mismatch() -> None:
    """``item.composite_id`` must equal ``decision.composite_id`` — no cross-wiring."""
    queue = InMemoryReviewQueue()
    log = InMemoryTrainingLog()
    item = queue.enqueue(_calibrated_item("s1"))
    bad = ReviewDecision(
        composite_id="totally/wrong/id",
        action=DecisionAction.ACCEPT,
        decided_by="pm@x.com",
    )
    with pytest.raises(ValueError):
        record_decision(item=item, decision=bad, log=log)
