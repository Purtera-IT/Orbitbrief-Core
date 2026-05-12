from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
IDF - INTERMEDIATE DISTRIBUTION FRAME
WM = WALL MOUNTED OUTLET 18" BELOW FINISHED CEILING
2. ALL CABLES SHALL BE LABELED AT BOTH ENDS, 6" FROM THE POINT OF TERMINATION.
3. PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
STANDARD CEILING MOUNTED TELECOMM 2-DATA OUTLET FOR WIRELESS ACCESS POINTS.
<PARSED TEXT FOR PAGE: 2 / 2>
TC301 TELECOMM RISER DIAGRAM
A/V CLOSET 031C
CONFERENCE ROOM 020
AP
PATCH PANEL A
""".strip()


def test_site_schematic_bundle_classifies_pages_and_observations() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="site-core",
            filename="drawing_packet.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        ),
        source_modality="site_schematic_pdf",
    )
    assert bundle.page_count == 2
    assert bundle.typed_pages == 2
    assert bundle.overlay_counts.get("wireless", 0) >= 1
    assert bundle.overlay_counts.get("low_voltage", 0) >= 1
    assert bundle.sheet_type_counts.get("legend_symbol", 0) == 1
    assert bundle.sheet_type_counts.get("riser_diagram", 0) == 1
    assert bundle.summary()["legend_entries"] >= 2
    assert bundle.summary()["note_clauses"] >= 1
    assert bundle.summary()["room_labels"] >= 1
    assert bundle.summary()["equipment_labels"] >= 1


SYMBOL_LINK_SAMPLE = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
WM = WALL MOUNTED OUTLET 18" BELOW FINISHED CEILING
CM = CEILING MOUNTED
AP WIRELESS ACCESS POINT OUTLET
3. PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
4. RED = WIRELESS
<PARSED TEXT FOR PAGE: 2 / 2>
TC100.2 LOWER LEVEL TELECOMM PLAN PART 2
CONFERENCE ROOM 020
AP
CM
""".strip()


def test_site_schematic_bundle_links_ap_like_symbols_to_packet_legend_rules() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="site-symbol-link",
            filename="drawing_packet.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SYMBOL_LINK_SAMPLE},
        ),
        source_modality="site_schematic_pdf",
    )
    assert bundle.summary()["regions"] >= 2
    assert bundle.summary()["symbol_instances"] >= 1
    ap_links = [link for link in bundle.symbol_links if link.symbol_token == "AP"]
    assert ap_links
    assert any(link.status == "linked" for link in ap_links)
    assert any(
        any("wireless" in clause.lower() or "patch panel" in clause.lower() for clause in link.related_note_clauses)
        for link in ap_links
    )
