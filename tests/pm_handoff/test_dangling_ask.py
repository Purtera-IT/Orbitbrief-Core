"""An ask that stops before it asks anything must never publish.

Clayton published "...who has the authority to?" and "...and what happens if?"
to a PM on 2026-08-13. Both cited real atoms and passed every gate: the quote
checker only inspects the QUOTED span, and these fragments dangle outside it.

The hard part is not catching them, it is NOT catching valid questions --
English strands prepositions constantly.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.pm_handoff.question_quality import dangling_tail_violation

# Real English questions a PM would legitimately ask. None may be flagged.
VALID = [
    "Who should I report to?",
    "What is this budget for?",
    "What is the enclosure made of?",
    "Which vendor is the rack supplied by?",
    "Who is the escort badge issued to?",
    "What room is the IDF in?",
    "Which floor is the display mounted on?",
    "Who pays for a wasted trip?",
    "With 428 sites, is this a fixed travel pool, and what happens if actual travel exceeds it?",
    "With 428 sites and concurrent crews, who has the authority to approve a reschedule?",
]

BROKEN = [
    ("With 428 sites and concurrent crews, who has the authority to?", "ask_cut_infinitive"),
    ("With 428 sites, is this a fixed travel pool, and what happens if?", "ask_dangling_tail"),
    ("Who confirms the site is open and?", "ask_dangling_tail"),
    ("Which crew owns the?", "ask_dangling_tail"),
    ("Does the customer have the right to?", "ask_cut_infinitive"),
    ("Is the charge per?", "ask_dangling_tail"),
]


@pytest.mark.parametrize("q", VALID)
def test_valid_questions_are_not_flagged(q):
    assert dangling_tail_violation(q) is None, q


@pytest.mark.parametrize("q,code", BROKEN)
def test_fragments_are_flagged(q, code):
    assert dangling_tail_violation(q) == code, q


def test_the_gate_is_wired_into_card_validation():
    from orbitbrief_core.pm_handoff.question_quality import validate_question_card

    card = {
        "rule_id": "llm.exposure.cancellation_charge_trigger",
        "suggested_open_question": (
            "With 428 sites and concurrent crews, who has the authority to?"
        ),
    }
    codes = {v.code for v in validate_question_card(card)}
    assert "ask_cut_infinitive" in codes
