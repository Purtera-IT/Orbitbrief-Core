"""Project-mode copy overrides pack-primary workstream labels."""
from __future__ import annotations

from orbitbrief_core.pm_handoff.builder import (
    _build_one_line_summary,
    _project_mode_workstream_label,
)
from orbitbrief_core.pm_handoff.models import DomainSummary, GapCard, SiteSummary
from orbitbrief_core.pm_handoff.reconciliation import build_executive_summary


def test_mode_label_overrides_maintenance_pack():
    assert _project_mode_workstream_label("network_edge_install") == "Network edge install"
    assert _project_mode_workstream_label("network_ops") is None
    assert _project_mode_workstream_label("generic") is None


def test_one_line_uses_edge_install_not_maintenance():
    domains = [
        DomainSummary(
            domain_id="network_maintenance",
            label="Network maintenance / operations",
            selected_by_router=True,
            active_for_sow=True,
            blockers=0,
            warnings=0,
            info=0,
            pack_name="Network maintenance / operations",
            score=0.8,
        )
    ]
    sites = [
        SiteSummary(name="Avon Office", kind="physical_site", publishable=True),
        SiteSummary(name="Brentwood Office", kind="physical_site", publishable=True),
    ]
    gaps = [
        GapCard(
            rule_id="q1",
            domain_id="project",
            domain_label="Project",
            label="Ask",
            severity="warning",
            message="ask",
            suggested_open_question="Which site is first?",
        )
    ]
    one = _build_one_line_summary(
        "deal-1", domains, sites, gaps, project_mode="network_edge_install"
    )
    assert "Network edge install" in one
    assert "maintenance" not in one.lower()


def test_exec_headline_uses_edge_install():
    domains = [
        DomainSummary(
            domain_id="network_maintenance",
            label="Network maintenance / operations",
            selected_by_router=True,
            active_for_sow=True,
            blockers=0,
            warnings=0,
            info=0,
            pack_name="Network maintenance / operations",
            score=0.8,
        )
    ]
    sites = [SiteSummary(name="Avon", kind="physical_site", publishable=True)]
    es = build_executive_summary(
        case_id="deal-1",
        status="yellow",
        status_label="review",
        one_line_summary="x",
        money_mentions=[],
        risks=[],
        gaps=[],
        sites=sites,
        domains=domains,
        project_mode="network_edge_install",
    )
    assert "Network edge install" in es.headline
    assert "maintenance" not in es.headline.lower()
    assert "Avon" in es.headline
    assert es.overview  # grounded briefing always present
    assert "Avon" in es.overview or "site" in es.overview.lower()


def test_exec_overview_is_multi_paragraph_briefing():
    sites = [SiteSummary(name="Avon", kind="physical_site", publishable=True)]
    domains = [
        DomainSummary(
            domain_id="av",
            label="AV install",
            selected_by_router=True,
            active_for_sow=True,
            blockers=0,
            warnings=0,
            info=0,
            pack_name="AV",
            score=0.5,
        )
    ]
    es = build_executive_summary(
        case_id="deal-1",
        status="green",
        status_label="ok",
        one_line_summary="**deal-1**: deal across 1 confirmed site(s) (Avon) covering AV install.",
        money_mentions=[],
        risks=[],
        gaps=[],
        sites=sites,
        domains=domains,
        project_mode="av_install",
    )
    assert es.overview != es.headline
    assert "\n\n" in es.overview
    assert "AV install" in es.headline or "AV" in es.headline
