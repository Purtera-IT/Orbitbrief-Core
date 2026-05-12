from __future__ import annotations

from orbitbrief_core.parser.site_schematic.extractors.common import enrich_detail_fact_clauses


def test_enrich_detail_fact_clauses_adds_wireless_detail_facts() -> None:
    text = """
AP CEILING OUTLET DETAIL
WALL PHONE OUTLET DETAIL
TYPICAL RISER SLEEVE DETAIL
BONDING DETAIL
J-HOOK DETAIL
LADDER RACK DETAIL
T568B JACK ASSIGNMENT
BOND EACH EQUIPMENT RACK TO GROUNDING BUSBAR WITH #4 AWG INSULATED GROUND WIRE.
DO NOT DAISY-CHAIN RACKS.
DO NOT BOND LADDER RACK OR CABLE TRAY TO EQUIPMENT RACKS.
""".strip()
    clauses = enrich_detail_fact_clauses(
        text=text,
        note_clauses=(),
        sheet_type="installation_detail",
        sheet_title="TC401",
    )
    lowered = " | ".join(clauses).lower()
    assert "j-hook detail" in lowered
    assert "t568b jack assignment detail" in lowered
    assert "do not daisy-chain racks" in lowered


def test_enrich_detail_fact_clauses_adds_low_voltage_equipment_facts() -> None:
    text = """
T904 RACK DETAILS
PATCH PANELS ARE 48-PORT DENSITY, 2U.
ADMIN OUTLET DATA CABLES TERMINATE ON DEDICATED PATCH PANELS.
18X6 CABLE TRAY OVERHEAD SUPPORT. LADDER RACK ALLOWED IN LOW CEILINGS.
ALL IDF/MDF CROSS-CONNECT FIELDS USE 110 BLOCKS.
UPS MINIMUM 15 MINUTES FOR ALL IT EQUIPMENT IN IDF AND MDF ROOMS.
""".strip()
    clauses = enrich_detail_fact_clauses(
        text=text,
        note_clauses=(),
        sheet_type="equipment_room_layout",
        sheet_title="T904",
    )
    lowered = " | ".join(clauses).lower()
    assert "48-port density 2u" in lowered
    assert "dedicated patch panels" in lowered
    assert "cross-connect fields use 110 blocks" in lowered
