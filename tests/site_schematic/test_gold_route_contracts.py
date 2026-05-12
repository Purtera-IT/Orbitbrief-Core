from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


WIRELESS_ROUTE_SAMPLE = """
<PARSED TEXT FOR PAGE: 1 / 3>
TC001 TELECOMM SYMBOL LIST
AP WIRELESS ACCESS POINT OUTLET
WM = WALL MOUNTED OUTLET 18" BELOW FINISHED CEILING
CM = CEILING MOUNTED
3. PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS.
4. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
5. FOR WIRELESS ACCESS POINTS, TC MOUNTS WAP BRACKET AND WAP, BOTH OWNER PROVIDED.
6. JACK COLORS: RED WIRELESS, GREEN CAMERAS, BLACK WALL PHONES, BLUE LAN.
<PARSED TEXT FOR PAGE: 2 / 3>
TC100 LOWER LEVEL TELECOMM PLAN OVERALL
CONFERENCE ROOM 020
IDF-2 TELECOMM CLOSET
AP CM AV CIP CSP2
RUN ALL TEL/DATA DEVICES ON THIS FLOOR TO NEAREST TELE DATA CLOSET.
<PARSED TEXT FOR PAGE: 3 / 3>
TC301 TELECOMM RISER DIAGRAM
25-PAIR CAT5E COPPER CABLE FROM MDF TO EACH IDF
12-STRAND SINGLEMODE FIBER FROM MDF TO EACH IDF
7. ALL TEL/DATA ROOMS SHALL BE TIED BACK TO MDF WITH #6 AWG GROUND.
PULL BOX REQUIRED FOR CONDUIT SECTION EXCEEDING 180 DEGREES BEND OR 100 FEET.
""".strip()


LOW_VOLTAGE_ROUTE_SAMPLE = """
<PARSED TEXT FOR PAGE: 1 / 3>
T000 PROJECT REQUIREMENTS NOTES & SPECS
1. ALL MDF, IDF AND AV ROOMS MAINTAIN 70F AND LESS THAN 60 PERCENT RH.
2. TGB 2X12 BUSBAR IN IDF, TMGB 4X12 BUSBAR IN MDF.
3. MINIMUM #6 AWG GREEN GROUNDING CONDUCTOR TO EACH EQUIPMENT RACK.
4. PULL BOX FOR EVERY 100 FEET OF STRAIGHT CONDUIT RUN.
5. ALL CONDUITS EMT UNLESS OTHERWISE NOTED.
6. WI-FI VENDOR RESPONSIBLE FOR SITE SURVEY BEFORE CEILING CLOSURE.
7. STRUCTURED CABLING WARRANTY 15 YEARS.
T901 CONDUIT RISER DIAGRAM
T902 CABLING RISER DIAGRAM
T903 MATV CABLING RISER DIAGRAM
T904 EQUIPMENT RACK DETAILS
T905 SECURITY INSTALLATION DETAILS
T906 INSTALLATION DETAILS
<PARSED TEXT FOR PAGE: 2 / 3>
T001 SYMBOLS & LEGENDS
# PORT ADMIN OUTLET
POS TERMINAL OUTLET
CEILING MOUNTED WIRELESS NODE OUTLET
DOOR CONTACT
CARD READER
MINI DOME CAMERA CEILING MOUNTED
1. ALL CABLING SHALL BE TESTED AND CERTIFIED.
2. LABEL CABLES AT BOTH ENDS.
<PARSED TEXT FOR PAGE: 3 / 3>
T904 EQUIPMENT RACK DETAILS
PATCH PANELS ARE 48-PORT DENSITY, 2U.
ADMIN OUTLET DATA CABLES TERMINATE ON DEDICATED PATCH PANELS.
ALL IDF/MDF CROSS-CONNECT FIELDS USE 110 BLOCKS.
UPS MINIMUM 15 MINUTES FOR IT EQUIPMENT IN IDF AND MDF ROOMS.
HOMERUN ALL CABLES ON THIS LEVEL TO MDF ROOM.
""".strip()


def _bundle(text: str):
    return build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="gold-contract",
            filename="gold.pdf",
            mime_type="application/pdf",
            metadata={"full_text": text},
        ),
        source_modality="site_schematic_pdf",
    )


def test_wireless_route_emits_structured_gold_contract_objects() -> None:
    bundle = _bundle(WIRELESS_ROUTE_SAMPLE)
    assert bundle.summary()["typed_pages"] == 3
    assert bundle.summary()["outlet_type_definitions"] >= 1
    assert bundle.summary()["service_loop_requirements"] >= 1
    assert bundle.summary()["termination_rules"] >= 1
    assert bundle.summary()["color_conventions"] >= 1
    assert bundle.summary()["grounding_requirements"] >= 1

    statuses = {row.status for row in bundle.note_clauses_structured}
    assert "owner_furnished" in statuses

    relations = {edge.relation for edge in bundle.graph.edges}
    assert {"matches_legend", "derived_from_note", "derived_from_legend", "terminates_at", "routed_to", "grounded_by"} <= relations


def test_low_voltage_route_emits_room_riser_and_requirements_contract() -> None:
    bundle = _bundle(LOW_VOLTAGE_ROUTE_SAMPLE)
    assert bundle.summary()["typed_pages"] == 3
    assert bundle.summary()["drawing_index_rows"] >= 6
    assert bundle.summary()["environmental_requirements"] >= 1
    assert bundle.summary()["grounding_requirements"] >= 1
    assert bundle.summary()["pathway_rules"] >= 1
    assert bundle.summary()["responsibility_assignments"] >= 1

    assert any("T906" in row.sheet_number for row in bundle.drawing_index_rows)
    assert any("rack" in rack.label.lower() for rack in bundle.racks)
    assert any("idf" in closet.label.lower() or "mdf" in closet.label.lower() for closet in bundle.closets)

    relations = {edge.relation for edge in bundle.graph.edges}
    assert {"appears_on_sheet", "defined_by", "requires", "constrained_by", "verified_by", "homeruns_to"} <= relations
