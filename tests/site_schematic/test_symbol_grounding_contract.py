from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import (
    SiteSchematicLegendEntry,
    SiteSchematicPrimitiveDetection,
    SiteSchematicSymbolInstance,
    build_site_schematic_bundle_from_router_input,
)
from orbitbrief_core.parser.site_schematic.symbols.detector import materialize_symbol_instances_from_detections
from orbitbrief_core.parser.site_schematic.symbols.linker import build_symbol_resolution_outcomes, link_symbol_instances


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
WM = WALL MOUNTED OUTLET
AP WIRELESS ACCESS POINT OUTLET
3. PROVIDE 20' OF CABLE SLACK FOR WIRELESS ACCESS POINTS. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
<PARSED TEXT FOR PAGE: 2 / 2>
TC100 FLOOR PLAN
CONFERENCE ROOM
AP
""".strip()


def test_symbol_input_contract_is_emitted_from_decomposition_hierarchy() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="symbol-contract",
            filename="symbol-contract.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        ),
        source_modality="site_schematic_pdf",
    )
    assert bundle.symbol_candidate_inputs
    first = bundle.symbol_candidate_inputs[0]
    assert first.artifact_id == "symbol-contract"
    assert first.page_index >= 1
    assert first.sheet_type
    assert first.source_mode
    assert first.provider
    assert first.decomposition_confidence >= 0.0
    assert isinstance(first.nearby_note_clauses, tuple)
    assert isinstance(first.nearby_legend_entry_ids, tuple)
    assert first.metadata.get("contract_version") == "symbol_input_v1"


def test_symbol_resolution_outcomes_capture_fail_closed_statuses() -> None:
    legends = (
        SiteSchematicLegendEntry(
            entry_id="legend:1",
            page_index=1,
            section="legend",
            label="Wireless Access Point",
            description="WAP wireless AP",
            primitive_kind="wireless_access_point",
            symbol_token="AP",
            confidence=0.8,
        ),
        SiteSchematicLegendEntry(
            entry_id="legend:2",
            page_index=1,
            section="legend",
            label="Access Point Device",
            description="AP access point outlet",
            primitive_kind="wireless_access_point",
            symbol_token="AP",
            confidence=0.8,
        ),
        SiteSchematicLegendEntry(
            entry_id="legend:3",
            page_index=1,
            section="legend",
            label="ZZ Camera Marker A",
            description="camera marker detail A",
            primitive_kind="camera_symbol",
            symbol_token="",
            confidence=0.8,
        ),
        SiteSchematicLegendEntry(
            entry_id="legend:4",
            page_index=1,
            section="legend",
            label="ZZ Camera Marker B",
            description="camera marker detail B",
            primitive_kind="camera_symbol",
            symbol_token="",
            confidence=0.8,
        ),
    )
    symbols = (
        SiteSchematicSymbolInstance(
            instance_id="sym:1",
            page_index=1,
            token="AP",
            primitive_kind="wireless_access_point",
            text="AP",
            confidence=0.92,
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:2",
            page_index=1,
            token="UNK",
            primitive_kind="unknown_symbol",
            text="UNK",
            confidence=0.33,
        ),
        SiteSchematicSymbolInstance(
            instance_id="sym:3",
            page_index=1,
            token="ZZ",
            primitive_kind="camera_symbol",
            text="ZZ",
                confidence=0.88,
            ),
            SiteSchematicSymbolInstance(
                instance_id="sym:4",
                page_index=1,
                token="CM",
                primitive_kind="camera_symbol",
                text="CM",
                confidence=0.41,
        ),
    )
    links = link_symbol_instances(
        symbol_instances=symbols,
        legend_entries=legends,
        note_clauses=(),
        room_labels=(),
    )
    outcomes = build_symbol_resolution_outcomes(
        symbol_instances=symbols,
        symbol_links=links,
        legend_entries=legends,
    )
    statuses = {row.status for row in outcomes}
    assert "conflicting" in statuses
    assert "detected_but_unmapped" in statuses
    assert "candidate_requires_review" in statuses
    assert "legend_defined_but_unused" in statuses


def test_future_detector_insert_path_materializes_instances() -> None:
    detections = (
        SiteSchematicPrimitiveDetection(
            detection_id="det:1",
            page_index=1,
            primitive_family="wap_ap",
            token_hint="AP",
            bbox=(0.1, 0.2, 0.3, 0.4),
            score=0.71,
            source_provider="future_detector",
            pseudo_page_id="pseudo:p1:1",
        ),
    )
    instances = materialize_symbol_instances_from_detections(
        detections=detections,
        overlay_tags=("wireless",),
        page_index=1,
        default_region_id="region:p1:1",
    )
    assert len(instances) == 1
    row = instances[0]
    assert row.token == "AP"
    assert row.primitive_kind == "wap_ap"
    assert row.source_mode == "future_detector"
    assert row.pseudo_page_id == "pseudo:p1:1"
