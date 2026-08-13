"""Deal-specific exposure asks must not be out-ranked out of existence.

Measured across three modes 2026-08-13 — all with 8 generated candidates and
7-8 admitted to the pool:

    av_install        pool 50 (at cap)  ->  0 published
    wireless_install  pool 32           ->  1 published
    staff_aug         pool 44           ->  3 published

The av_install brief dropped a contradiction between two documents in the deal
("3 primary room installations" vs "4 conference rooms") and an unconfirmed
union-labour surcharge, while publishing twelve generic coverage asks.
"""
from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.pm_handoff.question_engine import _reserve_exposure_slots


@dataclass
class _Card:
    rule_id: str


def _pool(n_tmpl: int, n_exp: int) -> list[_Card]:
    return [_Card(f"pmcover.t{i}") for i in range(n_tmpl)] + [
        _Card(f"llm.exposure.e{i}") for i in range(n_exp)
    ]


def test_exposure_gets_slots_when_shortlist_has_none():
    pool = _pool(20, 5)
    cards = [c for c in pool if not c.rule_id.startswith("llm.")][:12]
    out = _reserve_exposure_slots(cards, pool, cap=12, reserve=3)
    assert len(out) == 12
    assert sum(1 for c in out if c.rule_id.startswith("llm.exposure.")) == 3


def test_displaces_the_lowest_ranked_templates_not_the_top_ones():
    pool = _pool(20, 5)
    cards = [c for c in pool if not c.rule_id.startswith("llm.")][:12]
    out = _reserve_exposure_slots(cards, pool, cap=12, reserve=3)
    ids = {c.rule_id for c in out}
    assert "pmcover.t0" in ids and "pmcover.t1" in ids  # best coverage survives
    assert "pmcover.t11" not in ids  # tail is what gives way


def test_noop_when_generator_produced_nothing():
    pool = _pool(20, 0)
    cards = pool[:12]
    assert _reserve_exposure_slots(cards, pool, cap=12, reserve=3) == cards


def test_noop_when_quota_already_met():
    pool = _pool(20, 5)
    cards = [c for c in pool if c.rule_id.startswith("llm.")][:3] + [
        c for c in pool if not c.rule_id.startswith("llm.")
    ][:9]
    out = _reserve_exposure_slots(cards, pool, cap=12, reserve=3)
    assert out == cards


def test_never_exceeds_cap():
    pool = _pool(20, 5)
    cards = [c for c in pool if not c.rule_id.startswith("llm.")][:12]
    assert len(_reserve_exposure_slots(cards, pool, cap=12, reserve=3)) <= 12


def test_reserve_zero_disables():
    pool = _pool(20, 5)
    cards = [c for c in pool if not c.rule_id.startswith("llm.")][:12]
    assert _reserve_exposure_slots(cards, pool, cap=12, reserve=0) == cards


def test_only_promotes_cards_that_already_passed_the_pool():
    """Nothing is invented — promotion draws only from pool_cards."""
    pool = _pool(20, 2)
    cards = [c for c in pool if not c.rule_id.startswith("llm.")][:12]
    out = _reserve_exposure_slots(cards, pool, cap=12, reserve=3)
    promoted = [c for c in out if c.rule_id.startswith("llm.")]
    assert len(promoted) == 2  # only the two that existed
    assert all(c in pool for c in promoted)
