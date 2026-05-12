from __future__ import annotations

from orbitbrief_core.parser.site_schematic.models import SiteSchematicSymbolInstance
from orbitbrief_core.parser.site_schematic.symbols.detector import (
    map_symbol_instances_to_primitive_detections,
    materialize_symbol_instances_from_detections,
)
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import (
    build_first_pass_detector_class_map,
    map_ontology_class_to_detector_class,
)


def test_first_pass_detector_class_map_is_practical_size_and_explicit() -> None:
    mapping = build_first_pass_detector_class_map()
    detector_classes = mapping["detector_classes"]
    assert 20 <= len(detector_classes) <= 35
    assert mapping["ontology_to_detector"]
    assert mapping["deferred_ontology_classes"]


def test_ontology_to_detector_mapping_resolves_focus_classes() -> None:
    ap = map_ontology_class_to_detector_class("wireless_access_point_marker")
    pull = map_ontology_class_to_detector_class("pull_box_marker")
    jhook = map_ontology_class_to_detector_class("j_hook_pathway_symbol")
    assert ap["detector_class_id"]
    assert pull["detector_class_id"]
    assert jhook["detector_class_id"]
    assert ap["selected_for_first_pass"] is True


def test_detector_bridge_flow_maps_and_materializes_instances() -> None:
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:1",
            page_index=1,
            token="AP",
            primitive_kind="wireless_access_point",
            text="AP WIRELESS ACCESS POINT",
            confidence=0.8,
            region_id="region:p1:1",
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:2",
            page_index=1,
            token="AV",
            primitive_kind="device_symbol",
            text="AV OUTLET",
            confidence=0.76,
            region_id="region:p1:1",
        ),
    )
    detections = map_symbol_instances_to_primitive_detections(
        symbol_instances=symbols,
        packet_id="wireless",
    )
    assert detections
    assert all(row.primitive_family for row in detections)
    materialized = materialize_symbol_instances_from_detections(
        detections=detections,
        overlay_tags=("wireless",),
        page_index=1,
        default_region_id="region:p1:1",
    )
    assert len(materialized) == len(detections)
    assert all(row.source_mode == "heuristic_detector_bridge_v1" for row in materialized)
