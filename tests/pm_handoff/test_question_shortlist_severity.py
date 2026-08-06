"""Shortlist ordering: a warning must never displace an unresolved blocker.

The PM Review Queue is a capped slice of a much larger pool, and every real deal
saturates the cap. The one-per-family filter that builds the slice claims a
family for whichever card reaches it first, so walking raw pool order let a
warning take the slot and strand a same-family blocker outside the cap. Observed
live: deals shipping 3 blockers + 5 warnings with 23 blockers unshown in the pool.
"""

from orbitbrief_core.pm_handoff.business_labels import SEVERITY_SORT
from orbitbrief_core.pm_handoff.models import GapCard
from orbitbrief_core.pm_handoff.question_engine import (
    build_customer_questions,
    select_shortlist,
)

from tests.pm_handoff.test_question_engine import (
    _ops_junk_gaps,
    _sites,
    _sodexo_atoms,
)


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


# Two cards in the same "parking" family, one blocker and one warning, plus an
# unrelated blocker. In pool order the warning arrives first and claims the
# family; with cap=2 that strands the parking blocker outside the shortlist.
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


def test_warning_does_not_strand_a_same_family_blocker():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER]
    picked = select_shortlist(pool, cap=2)

    assert [c.severity for c in picked] == ["blocker", "blocker"], (
        "a warning took a shortlist slot while a blocker was left in the pool: "
        f"{[(c.severity, c.rule_id) for c in picked]}"
    )
    assert _PARKING_WARNING.rule_id not in {c.rule_id for c in picked}


def test_shortlist_orders_blockers_before_warnings():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER]
    picked = select_shortlist(pool, cap=10)
    ranks = [SEVERITY_SORT.get(c.severity, 9) for c in picked]
    assert ranks == sorted(ranks), [(c.severity, c.rule_id) for c in picked]


def test_cap_is_respected():
    pool = [_PARKING_WARNING, _POC_BLOCKER, _PARKING_BLOCKER]
    assert len(select_shortlist(pool, cap=1)) == 1
    # cap=0 is nonsense but must not return an unbounded queue.
    assert len(select_shortlist(pool, cap=0)) == 1


def test_real_deal_shortlist_is_severity_ordered():
    """End-to-end guard through the full engine, not just the helper."""
    cards, _ = build_customer_questions(
        gaps=_ops_junk_gaps(),
        sites=_sites(),
        envelope={"atoms": _sodexo_atoms()},
        feedback_events=[],
        cap=12,
    )
    ranks = [SEVERITY_SORT.get(c.severity, 9) for c in cards]
    assert ranks == sorted(ranks), [(c.severity, c.rule_id) for c in cards]
