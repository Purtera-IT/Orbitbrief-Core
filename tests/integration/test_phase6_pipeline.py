"""End-to-end Phase-6 wiring: brain → validator → calibrator → review queue.

Uses scripted LLM replies so the test is fast and deterministic.
The point is to verify the seams line up: every brain item ends
up either auto-accepted, queued for review, or rejected — and
every queued item produces a training record on decision.
"""
from __future__ import annotations

import json

import pytest

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.brains.managed_services import ManagedServicesBrain
from orbitbrief_core.calibrator import Calibrator
from orbitbrief_core.calibrator.verdict import Verdict
from orbitbrief_core.review_runtime import (
    DecisionAction,
    InMemoryReviewQueue,
    InMemoryTrainingLog,
    ReviewDecision,
    record_decision,
)
from orbitbrief_core.validator import (
    BrainOutputValidator,
    DictEvidenceLookup,
)
from orbitbrief_core.world_model.planner.schema import BriefState

from tests.brains.conftest import ScriptedChatClient


def _bundle() -> RetrievalBundle:
    return RetrievalBundle(
        project_id="p1",
        compile_id="c1",
        packets_by_family={
            "scope_inclusion": (
                PacketSnippet(
                    packet_id="pkt_s1",
                    family="scope_inclusion",
                    anchor_type="generic",
                    anchor_key="endpoint_monitoring",
                    status="active",
                    confidence=0.9,
                    governing_atom_ids=("a1",),
                    atom_text={"a1": "24x7 endpoint monitoring across 220 devices."},
                ),
            ),
            "scope_exclusion": (
                PacketSnippet(
                    packet_id="pkt_x1",
                    family="scope_exclusion",
                    anchor_type="generic",
                    anchor_key="hw",
                    status="active",
                    confidence=0.9,
                    governing_atom_ids=("a2",),
                    atom_text={"a2": "Hardware replacement out of scope."},
                ),
            ),
        },
    )


def _brief() -> BriefState:
    return BriefState(
        project_id="p1",
        compile_id="c1",
        generated_at="2026-01-01T00:00:00Z",
        pack_activations=(
            {"pack_id": "msp", "status": "active", "confidence": 0.9, "rationale": ""},  # type: ignore[arg-type]
        ),
        sites=(),
        claims=(),
        contradictions=(),
        review_flags=(),
        orchestration=(),
        model_used="qwen3:14b",
        tier="default",
        escalation_log={"metrics": {"pack_margin": 0.6}},
        token_cost={},
    )


def _lookup() -> DictEvidenceLookup:
    return DictEvidenceLookup(
        atoms={
            "a1": {"id": "a1", "verified": "verified", "locator": {"page": 5}},
            "a2": {"id": "a2", "verified": "verified", "locator": {"page": 12}},
        }
    )


def _payload() -> str:
    return json.dumps(
        {
            "project_id": "p1",
            "compile_id": "c1",
            "generated_at": "2026-01-01T00:00:00Z",
            "scope_items": [
                {
                    "id": "s1",
                    "statement": "24x7 endpoint monitoring across 220 devices.",
                    "supporting_packet_ids": ["pkt_s1"],
                    "supporting_atom_ids": ["a1"],
                    "confidence": 0.9,
                    "category": "monitoring",
                }
            ],
            "exclusions": [
                {
                    "id": "x1",
                    "statement": "Hardware replacement out of scope.",
                    "supporting_packet_ids": ["pkt_x1"],
                    "supporting_atom_ids": ["a2"],
                    "confidence": 0.9,
                    "rationale": "Explicit exclusion.",
                }
            ],
            "customer_responsibilities": [],
            "milestones": [],
            "assumptions": [],
            "dispatch_readiness_flags": [],
            "open_questions": [],
        }
    )


def test_pipeline_accepts_grounded_items_and_queues_borderline() -> None:
    """Brain output flows through validator + calibrator into the queue."""
    chat = ScriptedChatClient(replies=[_payload()])
    brain = ManagedServicesBrain(chat_client=chat)

    brief = _brief()
    bundle = _bundle()

    brain_result = brain.compose(brief, bundle)
    state = brain_result.state

    validator = BrainOutputValidator(lookup=_lookup())
    validation = validator.validate_managed_services(state, brief=brief, bundle=bundle)

    cal = Calibrator()
    cal_report = cal.calibrate_managed_services(
        state, validation=validation, brief=brief, bundle=bundle
    )

    # Both items should land — the calibrator labels them by verdict.
    assert len(cal_report.items) == 2
    by_verdict = cal_report.by_verdict()
    # In a clean envelope the borderline calibration may still route
    # to needs_review (caps + ambiguity penalty); the key is that no
    # item is REJECTed when the bundle / lookup are clean.
    assert Verdict.REJECT.value not in by_verdict

    queue = InMemoryReviewQueue()
    log = InMemoryTrainingLog()
    enqueued_ids: list[str] = []
    for item in cal_report.items:
        if item.verdict is Verdict.AUTO_ACCEPT:
            continue
        rev = queue.enqueue(item)
        enqueued_ids.append(rev.composite_id)

    # Reviewer accepts everything queued.
    for cid in enqueued_ids:
        decision = ReviewDecision(
            composite_id=cid,
            action=DecisionAction.ACCEPT,
            decided_by="pm@orbitbrief.dev",
            notes="ok",
        )
        item = queue.get(cid)
        assert item is not None
        queue.record_decision(decision)
        record_decision(item=item, decision=decision, log=log)

    assert len(log.all()) == len(enqueued_ids)
    assert all(r.accepted for r in log.all())


def test_pipeline_rejects_blocker_item() -> None:
    """A scope_item citing an unknown packet ⇒ validator BLOCKER ⇒ calibrator REJECT."""
    bad_payload = json.loads(_payload())
    bad_payload["scope_items"][0]["supporting_packet_ids"] = ["pkt_does_not_exist"]
    chat = ScriptedChatClient(replies=[json.dumps(bad_payload)])
    brain = ManagedServicesBrain(chat_client=chat)

    brief = _brief()
    bundle = _bundle()

    state = brain.compose(brief, bundle).state
    # The brain's post-call validator already strips the bad item;
    # we re-inject it directly to exercise the calibrator + validator
    # path on a brain output that wasn't already filtered.
    forced = state.model_copy(
        update={
            "scope_items": (
                # Build a ScopeItem citing a packet we know is missing.
                state.scope_items[0].model_copy(
                    update={
                        "supporting_packet_ids": ("pkt_does_not_exist",),
                        "supporting_atom_ids": (),
                    }
                ) if state.scope_items else None,
            )
        }
    ) if state.scope_items else state
    if not forced.scope_items or forced.scope_items[0] is None:
        # The brain stripped the only scope item; rebuild from the type.
        from orbitbrief_core.brains.managed_services.schema import ScopeItem

        forced = state.model_copy(
            update={
                "scope_items": (
                    ScopeItem(
                        id="s_ghost",
                        statement="bogus",
                        supporting_packet_ids=("pkt_does_not_exist",),
                        confidence=0.9,
                        category="phantom",
                    ),
                )
            }
        )

    validator = BrainOutputValidator(lookup=_lookup())
    validation = validator.validate_managed_services(
        forced, brief=brief, bundle=bundle
    )
    assert any(iv.has_blocker for iv in validation.items)

    cal_report = Calibrator().calibrate_managed_services(
        forced, validation=validation, brief=brief, bundle=bundle
    )
    by_verdict = cal_report.by_verdict()
    assert Verdict.REJECT.value in by_verdict
