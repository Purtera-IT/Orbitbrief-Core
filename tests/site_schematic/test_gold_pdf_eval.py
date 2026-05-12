from __future__ import annotations

import pytest

from .gold_eval import (
    LOW_VOLTAGE_FIXTURE,
    WIRELESS_FIXTURE,
    build_gold_scorecard,
    build_pdf_bundle,
    load_gold_fixture,
    resolve_fixture_pdf,
)

WIRELESS_PDF = resolve_fixture_pdf('wireless')
LOW_VOLTAGE_PDF = resolve_fixture_pdf('low_voltage')


def test_gold_fixtures_are_packaged_with_repo() -> None:
    assert WIRELESS_FIXTURE.exists()
    assert LOW_VOLTAGE_FIXTURE.exists()
    assert load_gold_fixture(WIRELESS_FIXTURE)["route_id"] == "wireless_ap_heavy_telecom_packet"
    assert load_gold_fixture(LOW_VOLTAGE_FIXTURE)["route_id"] == "low_voltage_hospitality_packet"


@pytest.mark.skipif(not WIRELESS_PDF.exists(), reason='wireless gold PDF not available in this environment')
def test_wireless_pdf_matches_gold_baseline_scorecard() -> None:
    gold = load_gold_fixture(WIRELESS_FIXTURE)
    bundle = build_pdf_bundle(WIRELESS_PDF)
    scorecard = build_gold_scorecard(bundle, gold)

    assert scorecard.page_count_match
    assert scorecard.typed_pages_match
    assert scorecard.sheet_type_counts_match
    assert scorecard.region_presence_match
    assert scorecard.minimum_output_keys_match
    assert scorecard.legality_status_match
    assert scorecard.graph_expectations_match
    assert all(scorecard.exact_anchor_checks.values())
    assert scorecard.critical_sections["critical_page_1_facts"] >= 0.95
    assert scorecard.critical_sections["critical_visual_tokens"] >= 0.95
    assert scorecard.critical_sections["critical_floorplan_facts"] >= 0.80
    assert scorecard.critical_sections["critical_riser_facts"] >= 0.90
    assert scorecard.critical_sections["critical_detail_facts"] >= 0.90


@pytest.mark.skipif(not LOW_VOLTAGE_PDF.exists(), reason='low-voltage gold PDF not available in this environment')
def test_low_voltage_pdf_matches_gold_baseline_scorecard() -> None:
    gold = load_gold_fixture(LOW_VOLTAGE_FIXTURE)
    bundle = build_pdf_bundle(LOW_VOLTAGE_PDF)
    scorecard = build_gold_scorecard(bundle, gold)

    assert scorecard.page_count_match
    assert scorecard.typed_pages_match
    assert scorecard.sheet_type_counts_match
    assert scorecard.region_presence_match
    assert scorecard.minimum_output_keys_match
    assert scorecard.legality_status_match
    assert scorecard.graph_expectations_match
    assert all(scorecard.exact_anchor_checks.values())
    assert scorecard.critical_sections["critical_page_1_facts"] >= 0.90
    assert scorecard.critical_sections["critical_page_2_symbol_tables"] >= 0.95
    assert scorecard.critical_sections["critical_device_and_outlet_types"] >= 0.90
    assert scorecard.critical_sections["critical_color_and_termination_facts"] >= 0.90
    assert scorecard.critical_sections["critical_floorplan_facts"] >= 0.85
    assert scorecard.critical_sections["critical_riser_facts"] >= 0.85
    assert scorecard.critical_sections["critical_equipment_room_and_detail_facts"] >= 0.90
