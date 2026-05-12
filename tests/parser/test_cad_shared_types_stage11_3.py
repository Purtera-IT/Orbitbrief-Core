from __future__ import annotations

from orbitbrief_core.parser.shared.types import (
    BBox,
    CalloutRef,
    ComponentKind,
    ComponentLabel,
    DiagramRelationHint,
    DrawingKind,
    PageRef,
    RegionKind,
    RelationHintKind,
    RevisionEntry,
    SheetRef,
    SpatialZone,
    TitleBlockField,
    VisualRegion,
)


def test_cad_shared_types_instantiate_and_serialize() -> None:
    page_ref = PageRef(page_index=1, page_label="A-101")
    bbox = BBox(1.0, 2.0, 3.0, 4.0, page_index=1, units="px")
    sheet = SheetRef(
        sheet_id="sheet:A-101",
        sheet_number="A-101",
        sheet_title="Network Floor Plan",
        drawing_kind=DrawingKind.FLOORPLAN,
        page_ref=page_ref,
        source_ref="doc:001",
        confidence=0.9,
    )
    region = VisualRegion(
        region_id="region:001",
        sheet_id=sheet.sheet_id,
        region_kind=RegionKind.TITLE_BLOCK,
        page_ref=page_ref,
        bbox=bbox,
        raw_text="Sheet Number: A-101",
        normalized_text="sheet number: a-101",
        source_ref="doc:001",
        confidence=0.88,
    )
    title = TitleBlockField(
        field_name="customer",
        field_value="Example Health",
        sheet_id=sheet.sheet_id,
        bbox=bbox,
        raw_text="Customer: Example Health",
        normalized_text="customer: example health",
        source_ref="doc:001",
        region_id=region.region_id,
        confidence=0.87,
    )
    rev = RevisionEntry(
        revision_code="A",
        revision_note="Added closet details",
        revision_id="rev:001",
        sheet_id=sheet.sheet_id,
        bbox=bbox,
        source_ref="doc:001",
        confidence=0.81,
    )
    callout = CalloutRef(
        callout_id="callout:001",
        label="Note 1",
        sheet_id=sheet.sheet_id,
        bbox=bbox,
        source_ref="doc:001",
        target_region_id=region.region_id,
        confidence=0.74,
    )
    component = ComponentLabel(
        component_id="component:001",
        label="AP-01",
        sheet_id=sheet.sheet_id,
        component_kind=ComponentKind.AP,
        bbox=bbox,
        source_ref="doc:001",
        zone_id="zone:001",
        confidence=0.8,
    )
    zone = SpatialZone(
        zone_id="zone:001",
        zone_name="MDF-01",
        sheet_id=sheet.sheet_id,
        zone_kind=RegionKind.CLOSET_LABEL,
        bbox=bbox,
        source_ref="doc:001",
        confidence=0.83,
    )
    hint = DiagramRelationHint(
        hint_id="hint:001",
        sheet_id=sheet.sheet_id,
        source_region_id=callout.callout_id,
        target_region_id=component.component_id,
        relation_kind=RelationHintKind.CALLOUT_FOR,
        confidence=0.66,
        reason="deterministic_pairing",
        source_ref="doc:001",
    )
    assert sheet.to_dict()["drawing_kind"] == "floorplan"
    assert region.to_dict()["region_kind"] == "title_block"
    assert title.to_dict()["field_name"] == "customer"
    assert rev.to_dict()["revision_code"] == "A"
    assert callout.to_dict()["target_region_id"] == region.region_id
    assert component.to_dict()["component_kind"] == "ap"
    assert zone.to_dict()["zone_kind"] == "closet_label"
    assert hint.to_dict()["relation_kind"] == "callout_for"

