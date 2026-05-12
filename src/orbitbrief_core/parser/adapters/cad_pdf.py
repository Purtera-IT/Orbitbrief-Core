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
class CadPdfConfig:
    default_authority: float = 0.78


class CadPdfAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="CadPdfAdapter",
        modality="cad_sheet",
        description="Deterministic CAD/PDF adapter that recovers drawing evidence primitives.",
    )

    def __init__(self, config: CadPdfConfig | None = None) -> None:
        self._config = config or CadPdfConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        extraction = extract_cad_structure(router_input)

        root = builder.add_section(title="DRAWING_PACKET", section_path=("DRAWING_PACKET",), metadata={"adapter": "cad_pdf", "synthetic": True})
        builder.set_section_root(root)
        sheet_title = extraction.sheet_title or "DRAWING_SHEET"
        sheet_path = ("DRAWING_PACKET", sheet_title)
        sheet_section = builder.add_section(
            title=sheet_title,
            section_path=sheet_path,
            parent_section_id=root,
            metadata={"adapter": "cad_pdf", "sheet_number": extraction.sheet_number or ""},
        )

        chronology = 0
        if extraction.sheet_number:
            sid = builder.add_span(
                text=f"Sheet Number: {extraction.sheet_number}",
                normalized_text=f"sheet number {extraction.sheet_number.lower()}",
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.9,
                metadata={"kind": "sheet_ref", "packet_families": ["drawing_metadata_packet"], "parser_cues": ["sheet_ref"]},
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1
        if extraction.sheet_title:
            sid = builder.add_span(
                text=f"Sheet Title: {extraction.sheet_title}",
                normalized_text=f"sheet title {extraction.sheet_title.lower()}",
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.88,
                metadata={"kind": "title_block", "packet_families": ["drawing_metadata_packet"], "parser_cues": ["sheet_title"]},
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for key, value in extraction.title_block_fields:
            sid = builder.add_span(
                text=f"{key}: {value}",
                normalized_text=f"{key} {value}".lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.86,
                metadata={
                    "kind": "title_block_field",
                    "region_kind": "title_block",
                    "packet_families": ["drawing_metadata_packet", "site_identity_packet"],
                    "parser_cues": ["title_block_field", "site_location"],
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for rev_code, rev_note in extraction.revision_entries:
            sid = builder.add_span(
                text=f"Rev {rev_code}: {rev_note}",
                normalized_text=f"rev {rev_code} {rev_note}".lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.82,
                metadata={
                    "kind": "revision_block",
                    "region_kind": "revision_block",
                    "packet_families": ["revision_change_packet"],
                    "parser_cues": ["revision_entry"],
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for value in extraction.note_lines:
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=self._config.default_authority,
                metadata={
                    "kind": "note_block",
                    "region_kind": "note_block",
                    "packet_families": ["note_scope_packet", "constructability_packet"],
                    "parser_cues": ["scope_included", "risk", "dependency", "customer_responsibility"],
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for value in extraction.callouts:
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.74,
                metadata={"kind": "callout", "region_kind": "callout", "packet_families": ["topology_hint_packet"], "parser_cues": ["open_question"]},
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for value in extraction.room_labels:
            family = "network_room_or_closet_packet" if any(token in value.lower() for token in ("mdf", "idf", "closet", "tr")) else "site_identity_packet"
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.83,
                metadata={
                    "kind": "room_label",
                    "region_kind": "room_label",
                    "packet_families": [family, "site_identity_packet"],
                    "parser_cues": ["site_location"],
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for value in extraction.equipment_labels:
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.8,
                metadata={
                    "kind": "equipment_label",
                    "region_kind": "equipment_label",
                    "packet_families": ["equipment_reference_packet", "known_quantity_packet", "constructability_packet"],
                    "parser_cues": ["quantity", "dependency"],
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for value in extraction.dimensions:
            sid = builder.add_span(
                text=value,
                normalized_text=value.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=0.76,
                metadata={"kind": "dimension_text", "region_kind": "dimension_text", "packet_families": ["known_quantity_packet"], "parser_cues": ["quantity"]},
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        for region in extraction.regions:
            if not region.text:
                continue
            bbox = region.bbox
            sid = builder.add_span(
                text=region.text,
                normalized_text=region.text.lower(),
                section_path=sheet_path,
                chronology_rank=chronology,
                authority_score=max(0.4, region.confidence),
                page_ref=region.page_index if region.page_index is not None else None,
                bbox=bbox if bbox is not None else None,
                metadata={
                    "kind": "visual_region",
                    "region_kind": region.kind,
                    "packet_families": ["drawing_metadata_packet"],
                    "parser_cues": ["visual_region"],
                    "region_id": region.region_id,
                },
            )
            builder.attach_span_to_section(sid, sheet_section)
            chronology += 1

        if extraction.review_required:
            add_flag(
                builder,
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.QUALITY,
                message="CAD sheet had weak structural recovery and requires review.",
                metadata={"adapter": "cad_pdf", "review_code": "cad_low_legibility"},
            )
        elif chronology == 0:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.AMBIGUITY,
                message="CAD sheet parsed but produced no recoverable structural regions.",
                metadata={"adapter": "cad_pdf"},
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
        site_bundle = build_site_schematic_bundle_from_router_input(router_input, source_modality="cad_sheet")
        metadata["site_schematic_bundle"] = site_bundle.to_dict()
        metadata["site_schematic_summary"] = site_bundle.summary()
        return replace(result, metadata=metadata)


def parse_cad_pdf(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return CadPdfAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)

