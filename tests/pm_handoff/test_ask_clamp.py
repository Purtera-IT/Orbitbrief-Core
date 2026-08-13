"""A clamped ask must still be a question a PM can answer.

normalize_pm_ask tail-clamped at 190 chars, which assumes the ask is
front-loaded. Generated exposure questions quote their evidence first, so the
clamp ate the actual question: Clayton shipped "...who has the authority to?"
and "...and what happens if?" to a PM on 2026-08-13. Both cite real atoms and
both are unanswerable.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.pm_ask_rewrite import normalize_pm_ask

CLAYTON = (
    "The SOW states 'Cancellation or reschedule 1 business day before scheduled "
    "visit—100% of total planned visit site costs.' With 428 sites and concurrent "
    "crews, who has the authority to approve a reschedule inside the 1-day window?"
)


def test_the_ask_survives_the_clamp():
    out = normalize_pm_ask(CLAYTON)
    assert len(out) <= 190
    assert out.endswith("?")
    # the verb+object that make it answerable
    assert "authority to approve" in out
    assert not out.endswith("authority to?")


def test_the_setup_is_what_gets_dropped():
    out = normalize_pm_ask(CLAYTON)
    assert "The SOW states" not in out
    assert "428 sites" in out  # the operative scale stays


def test_short_asks_are_untouched():
    short = "Who provides the badge for each site?"
    assert normalize_pm_ask(short) == short


def test_single_long_sentence_still_tail_clamps():
    # No sentence boundary to exploit; old behaviour is the fallback.
    q = "Who " + ("very " * 80) + "approves this?"
    out = normalize_pm_ask(q)
    assert len(out) <= 190
    assert out.endswith("?")


def test_never_returns_a_dangling_preposition():
    for q in (CLAYTON,):
        out = normalize_pm_ask(q)
        assert not out.rstrip("?").strip().endswith((" to", " if", " for", " of", " with"))
