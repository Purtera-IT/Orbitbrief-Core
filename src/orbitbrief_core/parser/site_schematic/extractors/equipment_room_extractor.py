from __future__ import annotations

from orbitbrief_core.parser.site_schematic.extractors.common import (
    ExtractedPageArtifacts,
    build_structured_rule_sets,
    enrich_detail_fact_clauses,
    extract_equipment_labels,
    extract_note_clauses,
    extract_room_labels,
)
from orbitbrief_core.parser.site_schematic.models import SiteSchematicNoteClause, SiteSchematicRegion
from orbitbrief_core.parser.site_schematic.zoning.page_zones import build_page_regions


def extract_equipment_room_sheet(
    *,
    page_index: int,
    text: str,
    sheet_title: str = "",
    regions: tuple[SiteSchematicRegion, ...] | None = None,
    pseudo_page_id: str = "",
    parent_region_id: str = "",
    subregion_role: str = "",
) -> ExtractedPageArtifacts:
    note_clauses = enrich_detail_fact_clauses(
        text=text,
        note_clauses=extract_note_clauses(text),
        sheet_type="equipment_room_layout",
        sheet_title=sheet_title,
    )
    structured = build_structured_rule_sets(page_index=page_index, clauses=note_clauses)
    base_regions = regions if regions is not None else build_page_regions(page_index=page_index, text=text, sheet_type="equipment_room_layout", sheet_title=sheet_title)
    extra_metadata = {"pseudo_page_id": pseudo_page_id, "parent_region_id": parent_region_id, "subregion_role": subregion_role}
    note_clause_objects = tuple(
        SiteSchematicNoteClause(
            clause_id=row.clause_id,
            page_index=row.page_index,
            text=row.text,
            clause_type=row.clause_type,
            confidence=row.confidence,
            status=row.status,
            scope_level=row.scope_level,
            scope_targets=row.scope_targets,
            parent_region_id=parent_region_id or row.parent_region_id,
            pseudo_page_id=pseudo_page_id or row.pseudo_page_id,
            bbox=row.bbox,
            source_mode=row.source_mode,
            metadata={**dict(row.metadata), **extra_metadata},
        )
        for row in structured["note_clause_objects"]
    )
    return ExtractedPageArtifacts(
        regions=base_regions,
        note_clauses=note_clauses,
        note_clause_objects=note_clause_objects,
        room_labels=extract_room_labels(text),
        equipment_labels=extract_equipment_labels(text),
        mounting_rules=structured["mounting_rules"],
        termination_rules=structured["termination_rules"],
        color_conventions=structured["color_conventions"],
        environmental_requirements=structured["environmental_requirements"],
        grounding_requirements=structured["grounding_requirements"],
        testing_requirements=structured["testing_requirements"],
        labeling_requirements=structured["labeling_requirements"],
        responsibility_assignments=structured["responsibility_assignments"],
        cable_rules=structured["cable_rules"],
        pathway_rules=structured["pathway_rules"],
        service_loop_requirements=structured["service_loop_requirements"],
        metadata=extra_metadata,
    )
