from __future__ import annotations

from orbitbrief_core.parser.site_schematic import SiteSchematicLegendEntry, SiteSchematicSymbolInstance
from orbitbrief_core.parser.site_schematic.symbols.linker import link_symbol_instances


def test_low_voltage_data_outlet_uses_detector_keywords_for_grounding() -> None:
    legends = (
        SiteSchematicLegendEntry(
            entry_id="legend:data",
            page_index=1,
            section="legend",
            label="Data outlet",
            description="CAT6 telecomm outlet",
            primitive_kind="outlet_glyph",
            symbol_token="",
            overlay_tags=("low_voltage",),
            confidence=0.8,
        ),
        SiteSchematicLegendEntry(
            entry_id="legend:door",
            page_index=1,
            section="legend",
            label="Door contact",
            description="security contact",
            primitive_kind="generic_marker",
            symbol_token="",
            overlay_tags=("low_voltage",),
            confidence=0.8,
        ),
    )
    symbol = SiteSchematicSymbolInstance(
        instance_id="sym:1",
        page_index=1,
        token="DATA",
        primitive_kind="data_outlet",
        text="guestroom data outlet at desk",
        confidence=0.89,
        overlay_tags=("low_voltage",),
        metadata={"detector_class_id": "data_outlet"},
    )
    links = link_symbol_instances(
        symbol_instances=(symbol,),
        legend_entries=legends,
        note_clauses=(),
        room_labels=(),
    )
    assert links[0].status == "linked"
    assert links[0].legend_entry_id == "legend:data"


def test_low_voltage_class_specific_thresholds_fail_closed_on_mismatch() -> None:
    legends = (
        SiteSchematicLegendEntry(
            entry_id="legend:data",
            page_index=1,
            section="legend",
            label="Data outlet",
            description="CAT6 telecomm outlet",
            primitive_kind="outlet_glyph",
            symbol_token="",
            overlay_tags=("low_voltage",),
            confidence=0.8,
        ),
    )
    symbol = SiteSchematicSymbolInstance(
        instance_id="sym:2",
        page_index=1,
        token="DC",
        primitive_kind="door_contact_marker",
        text="riser endpoint in idf",
        confidence=0.85,
        overlay_tags=("low_voltage",),
        metadata={"detector_class_id": "door_contact_marker"},
    )
    links = link_symbol_instances(
        symbol_instances=(symbol,),
        legend_entries=legends,
        note_clauses=("route backbone riser to MDF",),
        room_labels=("IDF",),
    )
    assert links[0].status in {"weakly_linked", "unresolved", "detected_but_unmapped"}
