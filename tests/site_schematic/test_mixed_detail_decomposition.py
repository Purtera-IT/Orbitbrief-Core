from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


MIXED_DETAIL_SAMPLE = """
<PARSED TEXT FOR PAGE: 1 / 1>
T900 ENLARGED EQUIPMENT ROOM LAYOUTS
GENERAL NOTES:
1. ALL TELECOM GROUNDING SHALL BOND TO TMGB.
2. VERIFY FIELD CONDITIONS PRIOR TO INSTALLATION.
DETAIL A - GUESTROOM MINI FLOOR PLAN
GUESTROOM DESK DATA OUTLET
CAT6 HOMERUN TO IDF
DETAIL B - MDF RACK ELEVATION
RACK ELEVATION WITH PATCH PANEL, BUSBAR, 110 BLOCK
DETAIL C - GROUNDING RISER DIAGRAM
TGB TO TMGB #6 AWG GREEN CONDUCTOR IN CONDUIT
""".strip()


def test_mixed_detail_page_emits_hierarchical_decomposition() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="mixed-detail",
            filename="t900.pdf",
            mime_type="application/pdf",
            metadata={"full_text": MIXED_DETAIL_SAMPLE},
        ),
        source_modality="site_schematic_pdf",
    )
    assert bundle.page_count == 1
    assert bundle.pages[0].sheet_type == "equipment_room_layout"
    assert len(bundle.regions) >= 2
    assert len(bundle.detail_regions) >= 2
    assert len(bundle.subregions) >= 2
    assert len(bundle.pseudo_pages) >= 2
    roles = {row.role for row in bundle.subregions}
    assert "equipment_elevation" in roles or "riser_diagram_fragment" in roles
