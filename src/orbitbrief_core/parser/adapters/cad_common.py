from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from orbitbrief_core.parser.adapters.common import extract_text
from orbitbrief_core.parser.router import RouterInput
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

_SHEET_NUMBER_RE = re.compile(r"\b([A-Z]{1,3}-?\d{1,3}(?:\.\d+)?)\b")
_TITLE_RE = re.compile(r"(?im)^\s*(?:sheet\s*title|title)\s*[:\-]\s*(.+)$")
_REV_RE = re.compile(r"(?im)^\s*(?:rev(?:ision)?)\s*([A-Z0-9]+)\s*[:\-]\s*(.+)$")
_TITLE_BLOCK_FIELD_RE = re.compile(r"(?im)^\s*(customer|client|site|address|project|drawn by|checked by|scale|date)\s*[:\-]\s*(.+)$")
_CALLOUT_RE = re.compile(r"\b(?:note|callout)\s*#?\s*\d+\b", re.IGNORECASE)
_ROOM_LABEL_RE = re.compile(r"\b(?:room|rm|closet|mdf|idf|tr)\s*[-#: ]?\s*([A-Z0-9\-]+)\b", re.IGNORECASE)
_EQUIPMENT_LABEL_RE = re.compile(r"\b(?:AP|SW|RACK|PANEL|UPS|PATCH)\s*[-_#]?\s*[A-Z0-9\-]+\b", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ft|feet|in|inch|m|meter|meters|sqft|sq\.?\s*ft)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CadRegion:
    region_id: str
    text: str
    kind: str
    page_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CadExtraction:
    sheet_number: str | None
    sheet_title: str | None
    title_block_fields: tuple[tuple[str, str], ...]
    revision_entries: tuple[tuple[str, str], ...]
    note_lines: tuple[str, ...]
    callouts: tuple[str, ...]
    room_labels: tuple[str, ...]
    equipment_labels: tuple[str, ...]
    dimensions: tuple[str, ...]
    review_required: bool
    raw_text: str
    regions: tuple[CadRegion, ...]


def _as_regions(router_input: RouterInput) -> tuple[CadRegion, ...]:
    payload = router_input.metadata.get("cad_regions") if isinstance(router_input.metadata, Mapping) else None
    if not isinstance(payload, list):
        return ()
    regions: list[CadRegion] = []
    for idx, row in enumerate(payload):
        if not isinstance(row, Mapping):
            continue
        region_id = str(row.get("region_id") or f"region:{idx:04d}")
        text = str(row.get("text") or "").strip()
        kind = str(row.get("kind") or row.get("region_kind") or "unknown").strip().lower() or "unknown"
        page_index = row.get("page_index")
        if not isinstance(page_index, int):
            page_index = None
        bbox = row.get("bbox")
        bbox_tuple: tuple[float, float, float, float] | None = None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                bbox_tuple = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            except (TypeError, ValueError):
                bbox_tuple = None
        confidence_raw = row.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(confidence_raw)))
        except (TypeError, ValueError):
            confidence = 0.0
        regions.append(
            CadRegion(
                region_id=region_id,
                text=text,
                kind=kind,
                page_index=page_index,
                bbox=bbox_tuple,
                confidence=confidence,
                metadata=dict(row),
            )
        )
    return tuple(regions)


def extract_cad_structure(router_input: RouterInput) -> CadExtraction:
    raw_text = extract_text(router_input)
    regions = _as_regions(router_input)
    if regions:
        joined = "\n".join(region.text for region in regions if region.text.strip())
        if joined.strip():
            raw_text = joined
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    lower_blob = " ".join(lines).lower()

    sheet_number = None
    sheet_number_match = _SHEET_NUMBER_RE.search(raw_text)
    if sheet_number_match:
        sheet_number = sheet_number_match.group(1).strip()

    sheet_title = None
    title_match = _TITLE_RE.search(raw_text)
    if title_match:
        sheet_title = title_match.group(1).strip()
    elif lines:
        first = lines[0]
        if len(first) <= 90 and any(token in first.lower() for token in ("plan", "diagram", "layout", "schematic", "floor")):
            sheet_title = first

    title_block_fields: list[tuple[str, str]] = []
    for match in _TITLE_BLOCK_FIELD_RE.finditer(raw_text):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if value:
            title_block_fields.append((key, value))

    revision_entries: list[tuple[str, str]] = []
    for match in _REV_RE.finditer(raw_text):
        revision_entries.append((match.group(1).strip(), match.group(2).strip()))

    note_lines = tuple(
        line for line in lines if line.lower().startswith(("note ", "notes:", "general notes", "install note", "support note"))
    )
    callouts = tuple(sorted({match.group(0).strip() for match in _CALLOUT_RE.finditer(raw_text)}))
    room_labels = tuple(sorted({match.group(0).strip() for match in _ROOM_LABEL_RE.finditer(raw_text)}))
    equipment_labels = tuple(sorted({match.group(0).strip() for match in _EQUIPMENT_LABEL_RE.finditer(raw_text)}))
    dimensions = tuple(sorted({match.group(0).strip() for match in _DIMENSION_RE.finditer(raw_text)}))

    has_structural_evidence = bool(
        sheet_number
        or sheet_title
        or title_block_fields
        or revision_entries
        or note_lines
        or callouts
        or room_labels
        or equipment_labels
        or dimensions
        or regions
    )
    weak_image_input = (
        isinstance(router_input.filename, str)
        and router_input.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        and len(raw_text.strip()) < 20
    )
    review_required = (not has_structural_evidence) or weak_image_input
    if "legend only" in lower_blob and not (room_labels or equipment_labels):
        review_required = True

    return CadExtraction(
        sheet_number=sheet_number,
        sheet_title=sheet_title,
        title_block_fields=tuple(title_block_fields),
        revision_entries=tuple(revision_entries),
        note_lines=note_lines,
        callouts=callouts,
        room_labels=room_labels,
        equipment_labels=equipment_labels,
        dimensions=dimensions,
        review_required=review_required,
        raw_text=raw_text,
        regions=regions,
    )


def _region_kind(value: str) -> RegionKind:
    lowered = str(value or "").strip().lower()
    mapping = {
        "title_block": RegionKind.TITLE_BLOCK,
        "revision_block": RegionKind.REVISION_BLOCK,
        "note_block": RegionKind.NOTE_BLOCK,
        "callout": RegionKind.CALLOUT,
        "room_label": RegionKind.ROOM_LABEL,
        "closet_label": RegionKind.CLOSET_LABEL,
        "equipment_label": RegionKind.EQUIPMENT_LABEL,
        "dimension_text": RegionKind.DIMENSION_TEXT,
        "legend": RegionKind.LEGEND,
        "unknown": RegionKind.UNKNOWN,
    }
    return mapping.get(lowered, RegionKind.UNKNOWN)


def _component_kind(text: str) -> ComponentKind:
    lower = text.lower()
    if "ap" in lower:
        return ComponentKind.AP
    if "rack" in lower:
        return ComponentKind.RACK
    if "switch" in lower or lower.startswith("sw"):
        return ComponentKind.SWITCH
    if "panel" in lower:
        return ComponentKind.PANEL
    if "cabinet" in lower:
        return ComponentKind.CABINET
    if "printer" in lower:
        return ComponentKind.PRINTER
    if "conference" in lower:
        return ComponentKind.CONFERENCE_ROOM
    return ComponentKind.UNKNOWN


def build_cad_evidence_bundle(
    extraction: CadExtraction,
    *,
    source_id: str,
    drawing_kind: DrawingKind = DrawingKind.UNKNOWN,
) -> dict[str, Any]:
    sheet_id = extraction.sheet_number or f"sheet:{source_id}"
    sheet_ref = SheetRef(
        sheet_id=sheet_id,
        sheet_number=extraction.sheet_number,
        sheet_title=extraction.sheet_title,
        drawing_kind=drawing_kind,
        source_ref=source_id,
        confidence=0.92 if extraction.sheet_number or extraction.sheet_title else 0.6,
        review_flag_ids=("cad_review_required",) if extraction.review_required else (),
    )

    visual_regions: list[VisualRegion] = []
    for region in extraction.regions:
        page_ref = PageRef(page_index=region.page_index) if region.page_index is not None else None
        bbox = BBox(*region.bbox, page_index=region.page_index) if region.bbox is not None else None
        visual_regions.append(
            VisualRegion(
                region_id=region.region_id,
                sheet_id=sheet_id,
                region_kind=_region_kind(region.kind),
                page_ref=page_ref,
                page_index=region.page_index,
                bbox=bbox,
                raw_text=region.text,
                normalized_text=region.text.lower(),
                source_ref=source_id,
                confidence=region.confidence,
                review_flag_ids=("cad_region_low_confidence",) if region.confidence < 0.45 else (),
                metadata=dict(region.metadata or {}),
            )
        )

    title_block_fields = tuple(
        TitleBlockField(
            field_name=key,
            field_value=value,
            sheet_id=sheet_id,
            raw_text=f"{key}: {value}",
            normalized_text=f"{key}: {value}".lower(),
            source_ref=source_id,
            confidence=0.86,
        )
        for key, value in extraction.title_block_fields
    )
    revision_entries = tuple(
        RevisionEntry(
            revision_id=f"rev:{idx:03d}",
            sheet_id=sheet_id,
            revision_code=code,
            revision_note=note,
            source_ref=source_id,
            confidence=0.82,
        )
        for idx, (code, note) in enumerate(extraction.revision_entries)
    )
    callouts = tuple(
        CalloutRef(
            callout_id=f"callout:{idx:03d}",
            label=value,
            sheet_id=sheet_id,
            source_ref=source_id,
            confidence=0.74,
        )
        for idx, value in enumerate(extraction.callouts)
    )
    components = tuple(
        ComponentLabel(
            component_id=f"component:{idx:03d}",
            label=value,
            sheet_id=sheet_id,
            component_kind=_component_kind(value),
            raw_text=value,
            normalized_text=value.lower(),
            source_ref=source_id,
            confidence=0.8,
        )
        for idx, value in enumerate(extraction.equipment_labels)
    )
    zones = tuple(
        SpatialZone(
            zone_id=f"zone:{idx:03d}",
            zone_name=value,
            sheet_id=sheet_id,
            zone_kind=RegionKind.CLOSET_LABEL if any(token in value.lower() for token in ("closet", "mdf", "idf")) else RegionKind.ROOM_LABEL,
            source_ref=source_id,
            confidence=0.83,
        )
        for idx, value in enumerate(extraction.room_labels)
    )

    relation_hints: list[DiagramRelationHint] = []
    for idx, callout in enumerate(callouts):
        if components:
            relation_hints.append(
                DiagramRelationHint(
                    hint_id=f"hint:callout_for:{idx:03d}",
                    sheet_id=sheet_id,
                    source_region_id=callout.callout_id,
                    target_region_id=components[min(idx, len(components) - 1)].component_id,
                    relation_kind=RelationHintKind.CALLOUT_FOR,
                    confidence=0.66,
                    reason="deterministic_callout_component_pairing",
                    source_ref=source_id,
                )
            )
    for idx, zone in enumerate(zones):
        for jdx, component in enumerate(components):
            if abs(idx - jdx) <= 2:
                relation_hints.append(
                    DiagramRelationHint(
                        hint_id=f"hint:component_in_zone:{idx:03d}:{jdx:03d}",
                        sheet_id=sheet_id,
                        source_region_id=component.component_id,
                        target_region_id=zone.zone_id,
                        relation_kind=RelationHintKind.COMPONENT_IN_ZONE,
                        confidence=0.62,
                        reason="deterministic_zone_component_proximity_hint",
                        source_ref=source_id,
                    )
                )

    return {
        "sheet_ref": sheet_ref.to_dict(),
        "visual_regions": [item.to_dict() for item in visual_regions],
        "title_block_fields": [item.to_dict() for item in title_block_fields],
        "revision_entries": [item.to_dict() for item in revision_entries],
        "callout_refs": [item.to_dict() for item in callouts],
        "component_labels": [item.to_dict() for item in components],
        "spatial_zones": [item.to_dict() for item in zones],
        "relation_hints": [item.to_dict() for item in relation_hints],
        "note_blocks": list(extraction.note_lines),
        "dimensions": list(extraction.dimensions),
        "review_required": extraction.review_required,
        "source_id": source_id,
    }

