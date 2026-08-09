"""The handoff must PROJECT the envelope, never re-derive it.

The envelope resolves each thing once. Every consumer that rebuilds its own
version of an already-canonical list eventually disagrees with it — silently,
because a brief with the wrong number still renders fine and reports success.

That is not hypothetical. `f257ba4` deleted **seven** duplicated builders. The
site panel was the eighth: it re-derived from `site_reality` clusters and
rendered a 437-site rollout as **3 entries named "hc 1023"** while
`site_readiness` sat in the same document with all 437 rows populated. Nothing
errored. It was found by a PM looking at a screen.

This test is the invariant that makes the ninth one fail in CI instead:

    what the PM sees == what the envelope resolved

The fixture is a verbatim slice of a real `envelope.json` pulled from blob. That
matters more than it sounds: four separate fixes for the bug above passed their
hand-written fixtures and changed nothing in production, because each fixture
matched the code rather than the artifact.
"""

import json
import shutil
from pathlib import Path

import pytest

from orbitbrief_core.pm_handoff.builder import _build_site_summaries

FIXTURE = Path(__file__).parent / "fixtures" / "envelope_conformance.json"


@pytest.fixture()
def case_dir(tmp_path: Path) -> Path:
    shutil.copy(FIXTURE, tmp_path / "envelope.json")
    return tmp_path


def _envelope() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_site_panel_matches_the_envelope_count(case_dir: Path):
    """The count a PM sees must equal the count the envelope resolved."""
    expected = len(_envelope()["site_readiness"]["sites"])
    actual = len(_build_site_summaries({}, case_dir))
    assert actual == expected, (
        f"panel shows {actual} sites, envelope resolved {expected} — "
        "a consumer is re-deriving instead of projecting"
    )


def test_site_panel_matches_the_declared_site_count(case_dir: Path):
    """Cross-check against the envelope's own declared total, not just the rows."""
    declared = _envelope()["site_readiness"]["site_count"]
    assert len(_build_site_summaries({}, case_dir)) == declared


def test_no_site_is_shown_as_a_raw_extractor_key(case_dir: Path):
    """`site:maricopa_county_...` is an internal key, never a label for a PM."""
    offenders = [
        s.name for s in _build_site_summaries({}, case_dir) if s.name.startswith("site:")
    ]
    assert not offenders, f"raw extractor keys leaked to the panel: {offenders[:3]}"


def test_every_shown_site_has_a_label(case_dir: Path):
    blank = [s for s in _build_site_summaries({}, case_dir) if not s.name.strip()]
    assert not blank, f"{len(blank)} site(s) would render with no label"


def test_panel_does_not_invent_sites(case_dir: Path):
    """Over-reporting is as wrong as dropping — the count must match exactly."""
    sites = _build_site_summaries({}, case_dir)
    assert len(sites) <= len(_envelope()["site_readiness"]["sites"])


def test_repeated_names_do_not_collapse_distinct_sites(case_dir: Path):
    """Two real sites may share a display name — they must both survive.

    A rollout genuinely contains three "Clayton Homes of Lexington" at different
    addresses. Deduping on the label rather than the site key would silently
    merge them and under-count the deal, which is the same failure this file
    exists to prevent, just from the opposite direction.
    """
    sites = _build_site_summaries({}, case_dir)
    names = [s.name for s in sites]
    assert len(names) > len(set(names)), (
        "fixture no longer contains a repeated site name — this test is vacuous"
    )
    assert len(sites) == len(_envelope()["site_readiness"]["sites"])
