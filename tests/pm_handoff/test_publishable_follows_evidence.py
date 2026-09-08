"""A site the parser never located is not a confirmed site.

`_sites_from_canonical_roster` hardcoded `publishable=True`, which is why the
brief and the parser disagreed on how many sites a deal has. The envelope row
carries `anchored` — the parser's own judgement — and the brief threw it away.
"""

from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import (
    _roster_row_is_publishable,
    _sites_from_canonical_roster,
)


def test_the_parsers_anchor_is_enough() -> None:
    assert _roster_row_is_publishable({"anchored": True}) is True


def test_any_location_at_all_is_enough() -> None:
    assert _roster_row_is_publishable({"anchored": False, "city": "Athens"}) is True
    assert _roster_row_is_publishable({"anchored": False, "address": "3300 Hillview Ave"}) is True
    assert _roster_row_is_publishable({"anchored": False, "zip": "94304"}) is True


def test_a_name_and_nothing_else_is_not_a_confirmed_site() -> None:
    assert _roster_row_is_publishable({"anchored": False}) is False
    # A blank is not a location.
    assert _roster_row_is_publishable({"anchored": False, "city": "   "}) is False


def test_the_symphony_case() -> None:
    """Live deal 010302: one office published twice, the second being the
    street of the first read as a place of its own."""
    envelope = {
        "site_readiness": {
            "sites": [
                {
                    "site": "site:palo_alto_ca_94304",
                    "name": "Palo Alto Office",
                    "address": "3300 Hillview Ave",
                    "city": "Palo Alto",
                    "state": "CA",
                    "anchored": True,
                    "signal_count": 4,
                },
                {
                    "site": "site:symphonyai_hillview_office",
                    "name": "Symphony Ai Hillview Office",
                    "anchored": False,
                    "signal_count": 2,
                },
            ]
        }
    }
    rows = _sites_from_canonical_roster(envelope, None)
    assert len(rows) == 2, "the row is not deleted — it still renders, as needs-review"
    published = [r for r in rows if r.publishable]
    assert [r.name for r in published] == ["Palo Alto Office"]


def test_duplicate_candidates_reach_the_brief() -> None:
    """parser-os proposes the pair; the brief has to carry it, or nobody is
    ever asked and the `same_site` head learns nothing."""
    from orbitbrief_core.pm_handoff.builder import _duplicate_candidates

    envelope = {
        "site_readiness": {
            "sites": [],
            "duplicate_candidates": [
                {
                    "unlocated": "site:symphonyai_hillview_office",
                    "located": "site:palo_alto_ca_94304",
                    "exemplar": "Palo Alto Office — 3300 Hillview Ave — Palo Alto, CA "
                                "|| Symphony Ai Hillview Office",
                    "shared_token": "hillview",
                    "why": "no address of its own",
                }
            ],
        }
    }
    out = _duplicate_candidates(envelope, None)
    assert len(out) == 1
    # The exemplar is the whole point: it must arrive intact, because the
    # answer is taught on exactly this string.
    assert out[0]["exemplar"].startswith("Palo Alto Office — 3300 Hillview Ave")


def test_no_candidates_is_an_empty_list_not_a_crash() -> None:
    from orbitbrief_core.pm_handoff.builder import _duplicate_candidates

    assert _duplicate_candidates({}, None) == []
    assert _duplicate_candidates({"site_readiness": []}, None) == []
    assert _duplicate_candidates({"site_readiness": {"sites": []}}, None) == []
