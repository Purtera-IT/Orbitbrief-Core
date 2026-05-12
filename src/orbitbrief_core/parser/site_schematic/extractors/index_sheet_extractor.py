from __future__ import annotations

from orbitbrief_core.parser.site_schematic.extractors.common import (
    ExtractedPageArtifacts,
    build_drawing_index_row_objects,
    build_drawing_index_row_objects_from_tables,
    build_structured_rule_sets,
    extract_drawing_index_rows,
    extract_drawing_index_rows_from_tables,
    extract_note_clauses,
)
from orbitbrief_core.parser.site_schematic.models import SiteSchematicUniversalTable
from orbitbrief_core.parser.site_schematic.zoning.page_zones import build_page_regions


def extract_index_sheet(
    *,
    page_index: int,
    text: str,
    sheet_title: str = "",
    universal_tables: tuple[SiteSchematicUniversalTable, ...] = (),
) -> ExtractedPageArtifacts:
    note_clauses = extract_note_clauses(text)
    drawing_rows = extract_drawing_index_rows_from_tables(universal_tables=universal_tables) or extract_drawing_index_rows(text)
    drawing_row_objects = build_drawing_index_row_objects_from_tables(page_index=page_index, universal_tables=universal_tables) or build_drawing_index_row_objects(page_index=page_index, rows=drawing_rows)
    structured = build_structured_rule_sets(page_index=page_index, clauses=note_clauses)
    return ExtractedPageArtifacts(
        regions=build_page_regions(page_index=page_index, text=text, sheet_type="schedule_sheet", sheet_title=sheet_title),
        note_clauses=note_clauses,
        note_clause_objects=structured["note_clause_objects"],
        drawing_index_rows=drawing_rows,
        drawing_index_row_objects=drawing_row_objects,
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
    )
