"""Shortlist selection invariants.

History worth keeping: this file originally pinned *severity-first* ordering,
on the reasoning that a warning must never displace an unresolved blocker. That
was measured and it was wrong — severity ordering scored 32.1% top-12 good rate
on held-out deals against 36.6% for leaving the pool order alone, because a
DeepSeek audit found 87% of cards labelled ``blocker`` were not worth asking.
Leading with severity promotes junk.

Ordering is now the question-quality head (47.5%); see
``test_question_quality_head.py``. What survives here are the invariants that
hold regardless of how the queue is ranked.
"""

from orbitbrief_core.pm_handoff.models import GapCard
from orbitbrief_core.pm_handoff.question_engine import select_shortlist


def _card(rule_id: str, severity: str, question: str) -> GapCard:
    return GapCard(
        rule_id=rule_id,
        domain_id="operations",
        domain_label="Operations",
        label="Ask",
        severity=severity,
        message=question,
        suggested_open_question=question,
    )


_PARKING_WARNING = _card(
    "pmcover.parking.fees",
    "warning",
    "Are parking fees at the Atmore site customer-reimbursed?",
)
_PARKING_BLOCKER = _card(
    "pmcover.parking.access",
    "blocker",
    "Are parking permits required for the Atmore site crew, and who pays?",
)
_POC_BLOCKER = _card(
    "pmcover.single_poc",
    "blocker",
    "Who is the single point of contact for cutover at each site?",
)


def test_cap_is_respected():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER]
    assert len(select_shortlist(pool, cap=1)) == 1
    # cap=0 is nonsense but must not return an unbounded queue.
    assert len(select_shortlist(pool, cap=0)) == 1


def test_no_duplicate_rule_ids():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER, _POC_BLOCKER]
    picked = select_shortlist(pool, cap=10)
    rule_ids = [c.rule_id for c in picked]
    assert len(rule_ids) == len(set(rule_ids))


def test_selection_is_deterministic():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER]
    first = [c.rule_id for c in select_shortlist(pool, cap=3)]
    assert first == [c.rule_id for c in select_shortlist(pool, cap=3)]


def test_empty_pool_is_safe():
    assert select_shortlist([], cap=12) == []
