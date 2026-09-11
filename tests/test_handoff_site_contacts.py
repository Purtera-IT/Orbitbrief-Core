"""A runbook has to know who to call at each site.

deal 000043's envelope roster holds a phone for 411 sites, an email for 410
and an access window for 401. The handoff carried each row's address and
dropped those, so "Customer POC is required" blocked every one of 434 sites.
"""

from __future__ import annotations

import json

from orbitbrief_core.pm_handoff.builder import _build_site_summaries, _clean_contact


def _envelope(tmp_path, rows):
    (tmp_path / "envelope.json").write_text(json.dumps({"site_readiness": {"sites": rows}}))
    return tmp_path


ROW = {
    "site": "site:hc_854",
    "aliases": ["HC-854", "Clayton Homes of Huntsville"],
    "facility_name": "Clayton Homes of Huntsville",
    "address": "730 I-45 South",
    "city": "Huntsville",
    "state": "TX",
    "zip": "77340",
    "phone": 9367308849,
    "email": "Lehn.Griepenstroh@ClaytonHomes.com",
    "access_window": "Mon-Fri 8a-5p",
    "anchored": True,
}


def test_the_store_contact_and_access_window_are_carried(tmp_path):
    [site] = _build_site_summaries({}, _envelope(tmp_path, [ROW]))
    assert site.email == "Lehn.Griepenstroh@ClaytonHomes.com"
    assert site.access_window == "Mon-Fri 8a-5p"


def test_a_phone_the_spreadsheet_gave_as_a_number_survives(tmp_path):
    """xlsx cells hand phone numbers over as integers."""
    [site] = _build_site_summaries({}, _envelope(tmp_path, [ROW]))
    assert site.phone == "9367308849"


def test_no_contact_name_is_invented(tmp_path):
    """The list has an email, not a name. Nothing here derives one."""
    [site] = _build_site_summaries({}, _envelope(tmp_path, [ROW]))
    assert not hasattr(site, "poc_name")


def test_a_site_without_contacts_still_builds(tmp_path):
    row = {k: v for k, v in ROW.items() if k not in ("phone", "email", "access_window")}
    [site] = _build_site_summaries({}, _envelope(tmp_path, [row]))
    assert site.phone is None and site.email is None and site.access_window is None
    assert site.address == "730 I-45 South"


def test_clean_contact():
    assert _clean_contact(None) is None
    assert _clean_contact("  ") is None
    assert _clean_contact(9367308849) == "9367308849"
    assert len(_clean_contact("x" * 500)) == 200
