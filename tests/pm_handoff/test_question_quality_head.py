"""Question-quality head: artifact integrity, scoring, and ordering."""

import json

from orbitbrief_core.pm_handoff.models import GapCard
from orbitbrief_core.pm_handoff.question_engine import select_shortlist
from orbitbrief_core.pm_handoff.question_quality_head import (
    _MODEL_PATH,
    load_model,
    probability,
    score_card,
)

# Verbatim live questions with their audit verdicts.
GOOD_ASK = "What are the approved work hours / blackout windows for install and cutover?"
BAD_ASK = (
    'Which quote wave includes "Termination. PCIGA may terminate this Purchase" '
    "— this wave, deferred, or out — CDW — at Atmore AL?"
)


def _card(question: str, severity: str = "warning", rule_id: str = "pmcover.x") -> GapCard:
    return GapCard(
        rule_id=rule_id,
        domain_id="operations",
        domain_label="Operations",
        label="Ask",
        severity=severity,
        message=question,
        suggested_open_question=question,
        sources=[{"filename": "rfp.pdf", "quote": "x" * 40}],
    )


def test_artifact_is_present_and_well_formed():
    model = load_model()
    assert model, "question_quality_model.json failed to load"
    assert model["kind"] == "question_quality_head"
    assert len(model["scores"]) > 1000
    assert model["fallback_weights"], "fallback model is empty"
    # Lexical n-grams overfit and must not be in the shipped weights.
    assert not [k for k in model["fallback_weights"] if k[:1] in "wb" and k[1:].isdigit()]


def test_artifact_is_valid_json_on_disk():
    with _MODEL_PATH.open(encoding="utf-8") as fh:
        json.load(fh)


def test_known_good_ask_outscores_known_bad_ask():
    assert score_card(_card(GOOD_ASK)) > score_card(_card(BAD_ASK))


def test_unseen_question_still_scores_via_fallback():
    novel = (
        "Who supplies the 48-port PoE switch for the Dallas IDF, and is it "
        "customer-furnished or PurTera-furnished?"
    )
    assert load_model()["scores"].get(novel.lower()) is None
    assert isinstance(score_card(_card(novel)), float)


def test_shortlist_orders_by_quality_not_severity():
    """A good warning must outrank a junk blocker — severity is 87% noise."""
    pool = [_card(BAD_ASK, severity="blocker", rule_id="scope.scope_item.abc123def456")]
    pool.append(_card(GOOD_ASK, severity="warning", rule_id="pmcover.work_hours"))
    picked = select_shortlist(pool, cap=2)
    assert picked[0].suggested_open_question == GOOD_ASK, [
        (c.severity, c.suggested_open_question[:40]) for c in picked
    ]


def test_shortlist_survives_a_missing_model(monkeypatch):
    """Ranking must never take the brief down."""
    import orbitbrief_core.pm_handoff.question_quality_head as head

    monkeypatch.setattr(head, "_MODEL", None)
    monkeypatch.setattr(head, "_MISSING", True)
    # Distinct families — one ask per family is enforced regardless of ranking.
    pool = [
        _card("What are the approved work hours for install and cutover?", rule_id="pmcover.work_hours"),
        _card("Are parking fees at the site customer-reimbursed?", rule_id="pmcover.parking"),
        _card("Who is the day-of onsite contact per site?", rule_id="pmcover.onsite_contact"),
    ]
    assert len(select_shortlist(pool, cap=3)) == 3


def test_probability_is_bounded():
    assert probability(-999) == 0.0
    assert probability(999) == 1.0
    assert 0.0 < probability(0.0) < 1.0
