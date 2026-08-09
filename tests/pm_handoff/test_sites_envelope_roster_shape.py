"""The site panel must read the envelope's roster in its ACTUAL shape.

The fixture is a verbatim slice of a real ``envelope.json`` pulled from blob —
not a hand-written dict. Three fixes shipped and did nothing in production
because each one asserted against an invented shape:

* ``site_readiness`` on the envelope is a **dict**, not a list; the rows are
  nested under ``sites``.
* A row keys the site as ``site`` ("site:hc_100"), not ``name``/``site_slug``.
* The facility name lives in ``aliases`` — ``["HC-100", "Clayton Homes of
  Laurinburg", "12021 Andrew Jackson Highway"]``.
* The worker writes ``envelope.json``; only the orchestrator uses ``00_``.

Every one of those reads as "no sites" and falls through to cluster derivation,
which is how a 437-site rollout kept rendering as 3 entries named "hc 1023".
"""

import json
import shutil
from pathlib import Path

from orbitbrief_core.pm_handoff.builder import (
    _display_name_from_aliases,
    _build_site_summaries,
    _roster_rows,
)

FIXTURE = Path(__file__).parent / "fixtures" / "envelope_site_roster.json"


def _envelope() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_roster_rows_reads_the_nested_dict_shape():
    assert len(_roster_rows(_envelope())) == 40


def test_roster_rows_still_reads_a_plain_list():
    assert len(_roster_rows({"site_readiness": [{"site": "site:a"}]})) == 1


def test_worker_path_returns_every_site(tmp_path):
    """Empty report + envelope.json on disk — exactly what the worker does."""
    shutil.copy(FIXTURE, tmp_path / "envelope.json")
    sites = _build_site_summaries({}, tmp_path)
    assert len(sites) == 40, f"got {len(sites)} — roster was not read"


def test_names_come_from_aliases_not_the_code(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "envelope.json")
    names = [s.name for s in _build_site_summaries({}, tmp_path)]
    assert any("Clayton Homes" in n for n in names), names[:5]
    assert not any(n.lower().startswith("hc ") and n[-1].isdigit() for n in names)


def test_alias_picker_skips_codes_and_addresses():
    aliases = ["HC-100", "Clayton Homes of Laurinburg", "12021 Andrew Jackson Highway"]
    assert _display_name_from_aliases(aliases) == "Clayton Homes of Laurinburg"
    # A code with nothing else is humanised rather than dropped — the site is
    # real even when the extractor found no facility name.
    assert _display_name_from_aliases(["HC-100"]) == "HC 100"
    assert _display_name_from_aliases(None) == ""


def test_envelope_json_is_preferred_over_the_orchestrator_name(tmp_path):
    """The worker writes envelope.json; 00_envelope.json is the other layout."""
    shutil.copy(FIXTURE, tmp_path / "envelope.json")
    assert len(_build_site_summaries({}, tmp_path)) == 40


def test_prose_sites_get_readable_labels():
    """Deals without a roster table carry only a slug, or a code plus address.

    Those are still real sites. Present what the row holds rather than printing
    the extractor's own key at a PM. Nothing is invented.
    """
    from orbitbrief_core.pm_handoff.builder import _display_name_from_aliases as f

    # Slug only.
    assert (
        f(["site:maricopa_county_iron_mountain_data_centers_azs_1_scottsdale"])
        == "Maricopa County Iron Mountain Data Centers Azs 1 Scottsdale"
    )
    # Code plus its address lines.
    assert (
        f(["MARICOPA-COUNTY", "615 N 48th St", "Phoenix, AZ 85008"])
        == "Maricopa County - 615 N 48th St, Phoenix, AZ 85008"
    )
    # A real name still wins over both.
    assert f(["HC-100", "Clayton Homes of Laurinburg", "12021 Andrew Jackson Highway"]) == (
        "Clayton Homes of Laurinburg"
    )


def test_acronyms_survive_humanising():
    from orbitbrief_core.pm_handoff.builder import _humanize_site_token as h

    # A lowercase slug carries no signal that "hc" is an acronym, so it is
    # title-cased. Only tokens that arrive uppercase are preserved.
    assert h("site:hc_100") == "Hc 100"
    assert h("HC-100") == "HC 100"
    assert h("MARICOPA-COUNTY") == "Maricopa County"
    assert h("site:dallas_idf_2") == "Dallas IDF 2"
