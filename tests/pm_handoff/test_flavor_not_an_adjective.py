"""'neat and workmanlike manner' is not a hardware brand.

The brand token matched a bare case-insensitive "Neat", and that phrase is
boilerplate in nearly every cabling SOW. On a real deal 2026-08-13 it tagged 8
of 12 PM questions:

    "Confirm access/escort/badging/after-hours requirements for ... — neat ·"

Neat IS a real video-conferencing brand, so it cannot simply be dropped — the
existing suite relies on "Neat bars", "Neat Devices" and "Neat + Yealink".
"""
from __future__ import annotations

import pytest

from orbitbrief_core.pm_handoff.pm_ask_rewrite import extract_deal_flavor

BOILERPLATE = [
    "Cabling will be installed in a neat and workmanlike manner, routed and dressed",
    "all work performed in a neat, professional manner",
    "cables shall be neat and orderly",
    "terminations shall present a neat appearance",
    "wiring to be neat; labelled at both ends",
]

REAL_BRAND = [
    "Cables noted for rerouting behind the wall; Neat bars + Yealink codecs.",
    "Is it possible to utilize white adapter to hang Neat Devices?",
    "install Neat Bar Pro units in each room",
]


@pytest.mark.parametrize("text", BOILERPLATE)
def test_adjective_is_not_a_brand(text):
    assert extract_deal_flavor(text) != "neat", text


@pytest.mark.parametrize("text", REAL_BRAND)
def test_real_brand_still_detected(text):
    got = extract_deal_flavor(text)
    assert got and "neat" in got.lower(), f"{text!r} -> {got!r}"


def test_a_competing_brand_may_win_but_something_is_detected():
    """"Neat + Yealink" resolves to the Yealink pattern first — still a brand.

    Note the Yealink pattern captures the following token as a model number, so
    this returns "Yealink in". Sloppy, but a real brand, and out of scope here.
    """
    got = extract_deal_flavor("4 TVs to Stay in Place; Neat + Yealink in the boardroom")
    assert got is not None
