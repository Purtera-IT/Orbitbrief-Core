from __future__ import annotations

from dataclasses import replace
from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.cad_common import build_cad_evidence_bundle, extract_cad_structure
from orbitbrief_core.parser.adapters.common import add_flag, make_builder
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import DrawingKind
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


@dataclass(frozen=True, slots=True)
class CadImageConfig:
    min_text_chars: int = 24


class CadImageAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="CadImageAdapter",
        modality="floorplan",
        description="Deterministic CAD/image adapter for floorplans and schematic screenshots.",
    )

    def __init__(self, config: CadImageConfig | None = None) -> None:
        self._config = config or CadImageConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        extraction = extract_cad_structure(router_input)
        root = builder.add_section(title="DRAWING_PACKET", section_path=("DRAWING_PACKET",), metadata={"adapter": "cad_image", "synthetic": True})
        builder.set_section_root(root)
        sheet = extraction.sheet_title or extraction.sheet_number or "IMAGE_SHEET"
        sheet_path = ("DRAWING_PACKET", sheet)
        section_id = builder.add_section(title=sheet, section_path=sheet_path, parent_section_id=root, metadata={"adapter": "cad_image"})

        chronology = 0
        for value in (*extraction.room_labels, *extraction.equipment_labels, *extraction.callouts, *extraction.dimensions):
            family = "constructability_packet"
            cue = "risk"
            kind = "cad_text"
            lower = value.lower()
            if any(token in lower for token in ("mdf", "idf", "closet", "room", "tr")):
                family = "network_room_or_closet_packet"
                cue = "site_location"
                kind = "room_label"
            elif any(token in lower for token in ("ap", "sw", "rack", "panel")):
                family = "equipment_reference_packet"
                cue = "quantity"
                kind = "equipment_label"
            elif "note" in lower or "callout" in lower:
                family = "note_scope_packet"
                cue = "scope_included"
                kind = "callout"
            elif any(unit in lower for unit in ("ft", "in", "meter", "sqft")):
                family = "known_quantity_packet"
                cue = "quantity"
                kind = "dimension_text"
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.72,
                metadata={"kind": kind, "packet_families": [family], "parser_cues": [cue], "source_modality": "cad_image"},
            )
            builder.attach_span_to_section(sid, section_id)
            chronology += 1

        for region in extraction.regions:
            if not region.text:
                continue
            sid = builder.add_span(
                text=region.text,
                normalized_text=region.text.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=max(0.35, region.confidence),
                page_ref=region.page_index if region.page_index is not None else None,
                bbox=region.bbox if region.bbox is not None else None,
                metadata={
                    "kind": "visual_region",
                    "region_kind": region.kind,
                    "packet_families": ["drawing_metadata_packet"],
                    "parser_cues": ["visual_region"],
                    "region_id": region.region_id,
                    "source_modality": "cad_image",
                },
            )
            builder.attach_span_to_section(sid, section_id)
            chronology += 1

        if extraction.review_required or len(extraction.raw_text.strip()) < self._config.min_text_chars:
            add_flag(
                builder,
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.QUALITY,
                message="CAD image had weak legibility and requires review/parking downstream.",
                metadata={"adapter": "cad_image", "review_code": "cad_image_weak_recovery"},
            )
        if chronology == 0:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.AMBIGUITY,
                message="CAD image produced no deterministic structural spans.",
                metadata={"adapter": "cad_image"},
            )
        result = builder.build()
        metadata = dict(result.metadata)
        drawing_kind = DrawingKind.FLOORPLAN
        modality = str(parse_plan.metadata.get("modality", "")).strip().lower() if hasattr(parse_plan.metadata, "get") else ""
        if modality == "schematic":
            drawing_kind = DrawingKind.ONE_LINE
        metadata["cad_evidence_bundle"] = build_cad_evidence_bundle(
            extraction,
            source_id=router_input.doc_id,
            drawing_kind=drawing_kind,
        )
        site_bundle = build_site_schematic_bundle_from_router_input(router_input, source_modality="site_schematic_image")
        metadata["site_schematic_bundle"] = site_bundle.to_dict()
        metadata["site_schematic_summary"] = site_bundle.summary()
        return replace(result, metadata=metadata)


def parse_cad_image(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return CadImageAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)

