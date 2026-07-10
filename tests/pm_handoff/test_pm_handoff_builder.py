from __future__ import annotations

import json
from pathlib import Path

import yaml

from orbitbrief_core.pm_handoff import build_pm_handoff, render_pm_handoff_markdown, render_sow_draft
from orbitbrief_core.pm_handoff.builder import _site_summaries_from_physical_atoms


def test_pm_handoff_hides_internal_language(tmp_path: Path):
    case = tmp_path / "CASE_001"
    (case / "synthesis").mkdir(parents=True)
    (case / "inspection_report.json").write_text(
        json.dumps(
            {
                "project_id": "CASE_001",
                "funnel": {"source_artifacts": 2, "atoms_extracted": 12, "packets_certified": 3},
                "pack_prior": {"top_pack_id": "low_voltage_cabling", "selected_pack_ids": ["low_voltage_cabling", "msp"]},
                "site_reality": {"clusters": [{"canonical_name": "Spring Lake High School - Auditorium Wing", "member_atom_ids": ["a1"], "artifact_ids": ["art1"]}]},
                "artifacts": [{"artifact_id": "art1", "filename": "site_list.csv", "artifact_type": "csv", "parser_name": "xlsx", "atom_count": 3}],
                "atom_lineage": [{"id": "atm1", "atom_type": "site_roster", "artifact_id": "art1", "text": "Site: Spring Lake High School - Auditorium Wing | Address: 16140 148th Ave", "locator": {"sheet": "Sites", "row": 2}, "confidence": 0.94, "verified": "verified", "downstream": {"bundled": True}}],
                "packets": [],
            }
        ),
        encoding="utf-8",
    )
    (case / "synthesis" / "site_reality.md").write_text("| cluster_id | canonical_name | kind | publishable |\n|---|---|---|---|\n| c1 | Spring Lake High School - Auditorium Wing | physical_site | true |\n", encoding="utf-8")
    (case / "sow_missingness.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "red",
                "active_domain_ids": ["low_voltage_cabling", "msp"],
                "findings": [
                    {
                        "rule_id": "low_voltage_cabling.testing_standard_missing",
                        "domain_id": "low_voltage_cabling",
                        "label": "Testing standard",
                        "severity": "blocker",
                        "message": "No testing standard found.",
                        "suggested_open_question": "What test standard is required?",
                        "observed_support": {"matched_regex": False, "publishable_site_count": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    handoff = build_pm_handoff(case)
    md = render_pm_handoff_markdown(handoff)

    assert handoff.status == "red"
    assert "Spring Lake High School" in md
    assert "What test standard is required?" in md
    assert "physical_site" in md
    assert "atom" not in md.lower()
    assert "pack prior" not in md.lower()
    assert "entity graph" not in md.lower()

    sow_md = render_sow_draft(handoff)
    assert "Statement of Work" in sow_md
    assert "Spring Lake High School" in sow_md
    assert "What test standard is required?" in sow_md


def test_site_summary_fallback_prefers_location_backed_physical_site():
    report = {
        "atoms": [
            {
                "id": "name_only",
                "atom_type": "physical_site",
                "entity_keys": ["site:gecko_robotics_pittsburgh_office_workshop"],
                "text": "Gecko Robotics requested assistance configuring a new Ubiquiti deployment for a new office/workshop location.",
                "value": {
                    "site_id": "GECKO-ROBOTICS-PITTSBURGH-OFFICE-WORKSHOP",
                    "name": "gecko robotics pittsburgh office workshop",
                },
            },
            {
                "id": "address",
                "atom_type": "physical_site",
                "entity_keys": ["site:pittsburgh_pa_15212"],
                "text": "100 S COMMONS STE 145, PITTSBURGH, PA 15212",
                "value": {
                    "site_id": "PITTSBURGH-PA-15212",
                    "name": "100 S COMMONS STE 145, PITTSBURGH, PA 15212",
                    "street_address": "100 S COMMONS STE 145",
                    "city": "PITTSBURGH",
                    "state": "PA",
                    "zip": "15212",
                },
            },
        ]
    }

    sites = _site_summaries_from_physical_atoms(report)

    assert len(sites) == 1
    assert sites[0].name == "100 S COMMONS STE 145, PITTSBURGH, PA 15212"
