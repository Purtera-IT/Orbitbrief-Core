from __future__ import annotations

import pytest

from tests.site_schematic.gold_eval import (
    LOW_VOLTAGE_FIXTURE,
    WIRELESS_FIXTURE,
    build_gold_scorecard,
    build_pdf_bundle,
    load_gold_fixture,
    resolve_fixture_pdf,
)

WIRELESS_PDF = resolve_fixture_pdf('wireless')
LOW_VOLTAGE_PDF = resolve_fixture_pdf('low_voltage')


@pytest.mark.skipif(not WIRELESS_PDF.exists(), reason='wireless gold PDF not available in this environment')
def test_wireless_gold_scorecard_serializes() -> None:
    scorecard = build_gold_scorecard(build_pdf_bundle(WIRELESS_PDF), load_gold_fixture(WIRELESS_FIXTURE))
    payload = scorecard.to_dict()
    assert payload['route_id'] == 'wireless_ap_heavy_telecom_packet'
    assert payload['page_count_match'] is True
    assert payload['critical_sections']['critical_page_1_facts'] >= 0.95


@pytest.mark.skipif(not LOW_VOLTAGE_PDF.exists(), reason='low-voltage gold PDF not available in this environment')
def test_low_voltage_gold_scorecard_serializes() -> None:
    scorecard = build_gold_scorecard(build_pdf_bundle(LOW_VOLTAGE_PDF), load_gold_fixture(LOW_VOLTAGE_FIXTURE))
    payload = scorecard.to_dict()
    assert payload['route_id'] == 'low_voltage_hospitality_packet'
    assert payload['graph_expectations_match'] is True
    assert payload['critical_sections']['critical_device_and_outlet_types'] >= 0.90
