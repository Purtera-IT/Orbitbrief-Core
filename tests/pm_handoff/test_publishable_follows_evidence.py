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
