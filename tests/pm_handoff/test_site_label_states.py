r"""A city must not be split in half because its last two letters spell a state.

Shipped to a PM on 2026-08-13 inside real questions:

    "Confirm access/escort/badging/after-hours requirements for Philadelph IA"

The separator between city and state was `\s*,?\s*` — which matches ZERO
characters — so a non-greedy city group happily consumed "Philadelph" and read
"ia" as Iowa. Same for Alexandria, Peoria, and (via CO) Waco.
"""
from __future__ import annotations

import pytest

from orbitbrief_core.pm_handoff.question_generators import _clean_site_label


@pytest.mark.parametrize("raw", [
    "Philadelphia 19120 - Philadelphia, PA 19120",
    "Alexandria 22314",
    "Peoria 61602",
    "Waco 76701",
    "Sofia 12345",
])
def test_city_is_never_split_mid_word(raw):
    out = _clean_site_label(raw)
    assert " IA" not in out or "Philadelphia" in out
    for bad in ("Philadelph IA", "Alexandr IA", "Peor IA", "Wa CO", "Sof IA"):
        assert bad not in out, f"{raw!r} -> {out!r}"


@pytest.mark.parametrize("raw,want", [
    ("location santa fe nm 87506", "Santa Fe NM"),
    ("Columbia, SC 29201", "Columbia SC"),
    ("Philadelphia, PA 19120", "Philadelphia PA"),
    ("site Austin TX 78701", "Austin TX"),
])
def test_real_city_state_still_normalizes(raw, want):
    assert _clean_site_label(raw) == want


def test_unparseable_label_is_left_alone():
    # Better to show the raw label than to invent a state.
    assert _clean_site_label("building 704") == "building 704"
