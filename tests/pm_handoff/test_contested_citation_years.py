"""A standards citation is not a quantity.

Measured on a real deal 2026-08-14, the contested-scope surface reported:

    device:rack   canonical_quantity=1992   competing=[6, 24]
      qty 1992  contractual_scope  rank 90
        "NUMBER: EIA-310 (Sep 1992) | TITLE: Racks, Panels and Associated Equipment"

1992 is the YEAR of the EIA-310 revision. It outranked the real claims because a
standards document is `contractual_scope` (rank 90) — so the false value did not
merely appear, it WON the canonical slot. "1992 racks" in front of a PM
discredits every genuine conflict on the page.
"""
from __future__ import annotations

from orbitbrief_core.risk_net.passthrough import _contested_scope_items, _is_citation_year


def _env(items):
    return {"scope_truth": {"contested": items}}


RACK = {
    "device": "device:rack", "site": "site:*", "canonical_quantity": 1992,
    "competing_values": [6, 24],
    "audit": [
        {"quantity": 1992, "claims": [{"quantity": 1992, "authority_rank": 90,
          "text": "NUMBER: EIA-310 (Sep 1992) | TITLE: Racks, Panels and Associated Equipment"}]},
        {"quantity": 6, "claims": [{"quantity": 6, "authority_rank": 40,
          "text": "Cat 6 patch cords for cabinet side connections."}]},
        {"quantity": 24, "claims": [{"quantity": 24, "authority_rank": 40,
          "text": "24 port patch panel per cabinet."}]},
    ],
}
REAL = {
    "device": "device:controller", "site": "site:*", "canonical_quantity": 2,
    "competing_values": [8],
    "audit": [
        {"quantity": 2, "claims": [{"quantity": 2, "authority_rank": 90,
          "text": "SOW - Premise Wiring, Bldg. 704 B-4"}]},
        {"quantity": 8, "claims": [{"quantity": 8, "authority_rank": 90,
          "text": "SOW - Premise Wiring, Bldg. 704 ii"}]},
    ],
}


def test_citation_year_is_recognised():
    assert _is_citation_year(1992, "NUMBER: EIA-310 (Sep 1992) | TITLE: Racks")
    assert _is_citation_year(2017, "ANSI/TIA-568.0-D published 2017")


def test_an_ordinary_quantity_that_looks_like_a_year_is_kept():
    """2024 drops in ordinary prose must survive — only citations are dropped."""
    assert not _is_citation_year(2024, "Install 2024 drops across the campus")
    assert not _is_citation_year(48, "Cat 6 48 port patch panel")


def test_the_citation_year_never_becomes_canonical():
    out = _contested_scope_items(_env([RACK]))
    for c in out:
        assert c["canonical_quantity"] != 1992
        assert 1992 not in c["competing_values"]


def test_a_genuine_conflict_survives_untouched():
    out = _contested_scope_items(_env([REAL]))
    assert len(out) == 1
    assert out[0]["canonical_quantity"] == 2
    assert out[0]["competing_values"] == [8]


def test_mixed_input_keeps_only_the_real_conflict():
    out = _contested_scope_items(_env([RACK, REAL]))
    devices = {c["device"] for c in out}
    assert "device:controller" in devices
    assert all(c["canonical_quantity"] != 1992 for c in out)


def test_empty_and_malformed_input_do_not_raise():
    assert _contested_scope_items({}) == []
    assert _contested_scope_items(_env([{}, None, "x"])) == []
