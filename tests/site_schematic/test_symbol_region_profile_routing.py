from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicLegendEntry, SiteSchematicSymbolInstance
from orbitbrief_core.parser.site_schematic.symbols.linker import link_symbol_instances
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import (
    profile_score_adjustment,
    profile_threshold_delta,
    select_profile_for_context,
)


def test_profile_selection_prefers_riser_context() -> None:
    profile_id, reasons = select_profile_for_context(
        sheet_type="riser_diagram",
        local_text="Backbone riser endpoint to MDF",
    )
    assert profile_id == "riser_profile"
    assert "riser_context" in reasons


def test_profile_selection_prefers_equipment_room_context() -> None:
    profile_id, reasons = select_profile_for_context(
        sheet_type="floorplan_detail",
        local_text="IDF room ladder rack and patch panel layout",
    )
    assert profile_id in {"equipment_room_profile", "rack_detail_profile"}
    assert reasons


def test_linker_respects_control_legend_profile_suppression() -> None:
    symbol = SiteSchematicSymbolInstance(
        instance_id="sym:p1:1",
        page_index=1,
        token="DATA",
        primitive_kind="data_symbol",
        text="DATA OUTLET LEGEND ROW",
        confidence=0.88,
        overlay_tags=("low_voltage",),
        region_id="r1",
        metadata={
            "detector_class_id": "data_outlet",
            "detector_profile_id": "control_legend_profile",
            "sheet_type": "legend_symbol",
            "region_kind": "legend_block",
        },
    )
    legend = SiteSchematicLegendEntry(
        entry_id="leg:1",
        page_index=1,
        section="legend",
        label="DATA OUTLET",
        description="DATA OUTLET",
        primitive_kind="data_symbol",
        symbol_token="DATA",
        confidence=0.9,
    )
    links = link_symbol_instances(
        symbol_instances=(symbol,),
        legend_entries=(legend,),
        note_clauses=(),
        room_labels=(),
    )
    assert links[0].status == "detected_but_unmapped"
    assert links[0].metadata.get("detector_profile_id") == "control_legend_profile"


def test_per_family_profile_deltas_are_directional_for_pressure_classes() -> None:
    assert profile_threshold_delta("rack_detail_profile", "data_outlet") > profile_threshold_delta("plan_body_profile", "data_outlet")
    assert profile_score_adjustment("riser_profile", "riser_endpoint") > profile_score_adjustment("plan_body_profile", "riser_endpoint")
    assert profile_score_adjustment("rack_detail_profile", "ladder_rack_cable_runway") > profile_score_adjustment("plan_body_profile", "ladder_rack_cable_runway")

