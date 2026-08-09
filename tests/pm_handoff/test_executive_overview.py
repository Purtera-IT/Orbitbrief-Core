"""The executive summary must carry its multi-paragraph overview.

ExecutiveSummary has had an `overview` field defined but nothing populating it,
so every brief shipped with three one-liners and a blank panel. The builder that
fills it (`pm_briefing.py`) existed only on an unmerged branch.

The overview is deterministic — built from the evidence pack, no LLM — so a
wedged inference host cannot empty it.
"""

from orbitbrief_core.pm_handoff.models import SiteSummary
from orbitbrief_core.pm_handoff.reconciliation import build_executive_summary


def _sites(n: int) -> list[SiteSummary]:
    return [
        SiteSummary(name=f"Clayton Homes of Town {i}", kind="physical_site", publishable=True)
        for i in range(n)
    ]


def _summary(**kw):
    return build_executive_summary(
        case_id="000043",
        status="red",
        status_label="Not SOW-ready",
        one_line_summary="Wireless install.",
        money_mentions=[],
        risks=[],
        gaps=[],
        sites=_sites(kw.pop("n_sites", 437)),
        domains=[],
        project_mode="wireless_install",
        **kw,
    )


def test_overview_is_populated():
    ov = _summary().overview
    assert len(ov) > 100, f"overview is {len(ov)} chars — the panel renders blank"


def test_overview_names_the_real_site_count():
    assert "437" in _summary().overview


def test_overview_needs_no_llm():
    """No chat client is passed anywhere — this must not depend on inference."""
    assert _summary(n_sites=3).overview.strip()


def test_optional_evidence_args_are_accepted():
    assert _summary(responsibilities=[], exclusions=[], fact_snippets=[], narrative_atoms=[]).overview


def test_three_one_liners_still_present():
    s = _summary()
    assert s.headline and s.health_line and s.next_action
