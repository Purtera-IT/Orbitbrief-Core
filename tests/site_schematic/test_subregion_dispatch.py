from __future__ import annotations

from orbitbrief_core.parser.site_schematic.extractors import extract_by_sheet_type
from orbitbrief_core.parser.site_schematic.models import SiteSchematicPseudoPage, SiteSchematicRegion


def test_subregion_dispatch_routes_mixed_detail_roles() -> None:
    regions = (
        SiteSchematicRegion(
            region_id="p1:detail_block",
            page_index=1,
            kind="detail_block",
            text="DETAIL A RACK ELEVATION",
            confidence=0.8,
        ),
    )
    pseudo = SiteSchematicPseudoPage(
        pseudo_page_id="pseudo:p1:1",
        page_index=1,
        parent_region_id="p1:detail_block",
        detail_region_id="detail:p1:r1:1",
        subregion_id="subregion:p1:1",
        role="equipment_elevation",
        text="RACK ELEVATION PATCH PANEL 110 BLOCK BUSBAR",
        confidence=0.8,
    )
    artifacts = extract_by_sheet_type(
        page_index=1,
        text="fallback",
        sheet_type="floorplan_detail",
        overlay_tags=("low_voltage",),
        sheet_title="T900",
        regions=regions,
        pseudo_page=pseudo,
    )
    assert artifacts.metadata.get("pseudo_page_id") == "pseudo:p1:1"
    assert any("rack" in row.lower() for row in artifacts.equipment_labels)
