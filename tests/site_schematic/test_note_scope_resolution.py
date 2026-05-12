from __future__ import annotations

from orbitbrief_core.parser.site_schematic.zoning.page_zones import (
    build_nested_detail_regions,
    build_page_regions,
    build_pseudo_pages,
    classify_subregions,
    resolve_note_scope,
)


def test_note_scope_resolution_marks_global_and_local() -> None:
    text = """
T900 ENLARGED EQUIPMENT ROOM LAYOUTS
GENERAL NOTES
1. ALL RACKS SHALL BE BONDED TO BUSBAR.
DETAIL A - EQUIPMENT ELEVATION
PATCH PANEL AND RACK DETAIL
DETAIL B - GUESTROOM MINI FLOOR PLAN
GUESTROOM DATA OUTLET DETAIL
""".strip()
    regions = build_page_regions(page_index=1, text=text, sheet_type="equipment_room_layout", sheet_title="T900")
    detail_regions = build_nested_detail_regions(page_index=1, text=text, regions=regions, sheet_type="equipment_room_layout")
    subregions = classify_subregions(page_index=1, sheet_type="equipment_room_layout", detail_regions=detail_regions)
    pseudo_pages = build_pseudo_pages(page_index=1, sheet_type="equipment_room_layout", text=text, regions=regions, subregions=subregions)
    links = resolve_note_scope(
        page_index=1,
        note_clauses=(
            "ALL RACKS SHALL BE BONDED TO BUSBAR.",
            "DETAIL A SHALL USE DEDICATED PATCH PANEL.",
            "DETAIL A AND DETAIL B SHARE SAME CABLE TRAY RULE.",
        ),
        regions=regions,
        subregions=subregions,
        pseudo_pages=pseudo_pages,
    )
    assert len(links) == 3
    assert links[0].scope_level in {"page_global", "subregion_local"}
    assert links[1].scope_level == "subregion_local"
    assert links[2].status in {"unresolved", "scoped"}


def test_general_notes_remain_page_global_when_multiple_targets() -> None:
    text = """
T900 ENLARGED EQUIPMENT ROOM LAYOUTS
GENERAL NOTES
1. VERIFY ALL FIELD CONDITIONS.
2. COORDINATE RACK BONDING WITH ELECTRICAL.
DETAIL A - EQUIPMENT ELEVATION
DETAIL B - RISER DIAGRAM
""".strip()
    regions = build_page_regions(page_index=1, text=text, sheet_type="equipment_room_layout", sheet_title="T900")
    detail_regions = build_nested_detail_regions(page_index=1, text=text, regions=regions, sheet_type="equipment_room_layout")
    subregions = classify_subregions(page_index=1, sheet_type="equipment_room_layout", detail_regions=detail_regions)
    pseudo_pages = build_pseudo_pages(page_index=1, sheet_type="equipment_room_layout", text=text, regions=regions, subregions=subregions)
    links = resolve_note_scope(
        page_index=1,
        note_clauses=("GENERAL NOTES: VERIFY ALL FIELD CONDITIONS AND COORDINATE RACK BONDING.",),
        regions=regions,
        subregions=subregions,
        pseudo_pages=pseudo_pages,
    )
    assert len(links) == 1
    assert links[0].scope_level == "page_global"
    assert links[0].status == "scoped"
