"""The mode is in the artifact; what decided it was not.

`service_routing.primary` decides `project_mode`, which decides which questions
the PM is asked — and none of that reasoning reached PM_HANDOFF.json. Auditing
three deals 2026-08-13 I read routing as broken ("absent on every deal") when it
was working correctly and overriding a bad head:

    01491cca  llm_scope_router -> low_voltage_cabling  (head agreed)
    02557291  llm_scope_router -> staff_augmentation   (head said `wireless`)

Only the banked router_training_rows.jsonl showed it. That is too well hidden
for a decision this load-bearing.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.question_engine import _routing_provenance


def test_llm_rung_is_identifiable():
    out = _routing_provenance({
        "enabled": True, "primary": "staff_augmentation",
        "source": "llm_scope_router", "confidence": 0.9,
    })
    assert out["decided"] is True
    assert out["primary"] == "staff_augmentation"
    assert out["source"] == "llm_scope_router"


def test_head_passthrough_is_distinguishable_from_the_llm():
    """The head measured 0.529 and answered `wireless` six times running."""
    out = _routing_provenance({
        "enabled": True, "primary": "wireless",
        "source": "service_router_head", "confidence": 0.8,
    })
    assert out["source"] == "service_router_head"


def test_no_opinion_is_reported_not_omitted():
    """`{}` is a deliberate answer — it leaves the keyword cascade in charge."""
    assert _routing_provenance({}) == {"decided": False}
    assert _routing_provenance(None) == {"decided": False}


def test_abstention_reason_survives():
    out = _routing_provenance({
        "primary": "", "source": "head", "abstained": True,
        "abstain_reason": "below threshold",
    })
    assert out["abstained"] is True
    assert out["abstain_reason"] == "below threshold"


def test_scope_summary_is_hashed_not_inlined():
    out = _routing_provenance({
        "primary": "wireless", "source": "head",
        "scope_summary": "x" * 5000, "scope_summary_sha256": "abc123",
    })
    assert out["scope_summary_sha256"] == "abc123"
    assert "scope_summary" not in out


def test_it_lands_in_the_question_meta():
    from orbitbrief_core.pm_handoff.question_engine import build_customer_questions

    _cards, meta = build_customer_questions(
        gaps=[], sites=[],
        envelope={"service_routing": {"primary": "staff_augmentation",
                                      "source": "llm_scope_router"}},
    )
    assert meta["service_routing"]["source"] == "llm_scope_router"
