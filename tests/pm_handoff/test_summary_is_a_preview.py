"""The one-liner should preview the deal, not restate the metadata.

Audited 2026-08-13 — 97 characters of pure status:

    "000050: Staff augmentation at Site 1, Site 2; 9 blocker and 3
     clarification(s) need PM/SA review."

Nothing about what is being installed, when, or what is actually blocking.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import _build_one_line_summary
from orbitbrief_core.pm_handoff.models import GapCard, SiteSummary

SITES = [SiteSummary(name="Site 1", kind="physical_site", publishable=True)]
GAPS = [
    GapCard(rule_id="r1", domain_id="d", domain_label="D", label="Pathway ownership",
            severity="blocker", message="m", suggested_open_question="q?"),
    GapCard(rule_id="r2", domain_id="d", domain_label="D", label="CF vs OFE hardware",
            severity="blocker", message="m", suggested_open_question="q?"),
    GapCard(rule_id="r3", domain_id="d", domain_label="D", label="Minor",
            severity="warning", message="m", suggested_open_question="q?"),
]
ROLLS = [{"site_key": "s1", "site_name": "S1", "devices": ["access point"]}]


def _run(**kw):
    return _build_one_line_summary("D-1", [], SITES, GAPS, project_mode="staff_aug", **kw)


def test_equipment_appears_and_is_pluralised():
    out = _run(site_rollups=ROLLS)
    assert "access points" in out


def test_leading_blockers_are_named_not_just_counted():
    out = _run(site_rollups=ROLLS)
    assert "Pathway ownership" in out and "CF vs OFE hardware" in out
    assert "2 blocker" in out


def test_a_plausible_window_is_shown():
    out = _run(date_mentions=[{"iso": "2026-04-10"}, {"iso": "2026-07-17"}])
    assert "2026-04-10 to 2026-07-17" in out


def test_a_contaminated_window_is_suppressed():
    """A real deal swept in a 2022 boilerplate date beside 2026 ones.

    Printing 2022-10-01 to 2026-05-26 as the project window states something
    false with the authority of a headline.
    """
    out = _run(date_mentions=[{"iso": "2022-10-01"}, {"iso": "2026-05-26"}])
    assert "2022-10-01" not in out


def test_single_date_is_not_called_a_window():
    out = _run(date_mentions=[{"iso": "2026-04-10"}])
    assert "dated 2026-04-10" in out and " to " not in out


def test_no_dollar_figure_is_invented():
    """margin_view reported deal_total 0 at low confidence on every audited deal."""
    out = _run(site_rollups=ROLLS, date_mentions=[{"iso": "2026-04-10"}])
    assert "$" not in out


def test_still_works_with_no_extra_facts():
    out = _build_one_line_summary("D-1", [], SITES, GAPS, project_mode="staff_aug")
    assert "Staff augmentation" in out and out.endswith(".")


def test_it_is_materially_longer_than_the_old_status_line():
    out = _run(site_rollups=ROLLS, date_mentions=[{"iso": "2026-04-10"}, {"iso": "2026-07-17"}])
    assert len(out) > 140


def test_equipment_nouns_pluralise_correctly():
    """"switchs" and "storages" both reached a live brief headline."""
    from orbitbrief_core.pm_handoff.builder import _plural

    assert _plural("switch") == "switches"
    assert _plural("box") == "boxes"
    assert _plural("battery") == "batteries"
    assert _plural("storage") == "storage"      # uncountable
    assert _plural("cabling") == "cabling"      # uncountable
    assert _plural("displays") == "displays"    # already plural


def test_deal_specific_blockers_lead_over_templates():
    """The same two template labels led three different briefs verbatim."""
    tmpl = [
        GapCard(rule_id="pmcover.pathway", domain_id="d", domain_label="D",
                label="Pathway ownership", severity="blocker", message="m",
                suggested_open_question="q?"),
        GapCard(rule_id="pmcover.furnish", domain_id="d", domain_label="D",
                label="CF vs OFE hardware", severity="blocker", message="m",
                suggested_open_question="q?"),
    ]
    specific = GapCard(rule_id="llm.exposure.union_labor", domain_id="d",
                       domain_label="D", label="Union labour surcharge",
                       severity="blocker", message="m", suggested_open_question="q?")
    out = _build_one_line_summary("D-1", [], SITES, tmpl + [specific],
                                  project_mode="av_install")
    assert "Union labour surcharge" in out
