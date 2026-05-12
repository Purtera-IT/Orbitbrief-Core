from __future__ import annotations

from typing import Any

from orbitbrief_core.parser.site_schematic.extractors.common import (
    ExtractedPageArtifacts,
    build_drawing_index_row_objects,
    build_drawing_index_row_objects_from_tables,
    build_structured_rule_sets,
    extract_drawing_index_rows,
    extract_drawing_index_rows_from_tables,
    extract_equipment_labels,
    extract_note_clauses,
    extract_room_labels,
    should_extract_drawing_index_for_notes_spec,
)
from orbitbrief_core.parser.site_schematic.models import SiteSchematicUniversalTable
from orbitbrief_core.parser.site_schematic.zoning.page_zones import build_page_regions


def extract_notes_spec_sheet(
    *,
    page_index: int,
    text: str,
    sheet_title: str = "",
    universal_tables: tuple[SiteSchematicUniversalTable, ...] = (),
    promoted_note_candidates: tuple[dict[str, Any], ...] = (),
) -> ExtractedPageArtifacts:
    note_clauses = extract_note_clauses(text)
    if not note_clauses and promoted_note_candidates:
        promoted_text = tuple((row.get("text", "") or "").strip() for row in promoted_note_candidates if (row.get("text", "") or "").strip())
        note_clauses = tuple(dict.fromkeys(promoted_text))
    table_drawing_rows = extract_drawing_index_rows_from_tables(universal_tables=universal_tables)
    text_drawing_rows = extract_drawing_index_rows(text)
    use_drawing_rows = should_extract_drawing_index_for_notes_spec(
        text=text,
        table_row_texts=table_drawing_rows,
        text_row_texts=text_drawing_rows,
    )
    drawing_rows = (table_drawing_rows or text_drawing_rows) if use_drawing_rows else ()
    drawing_row_objects = (
        build_drawing_index_row_objects_from_tables(page_index=page_index, universal_tables=universal_tables)
        if table_drawing_rows and use_drawing_rows
        else build_drawing_index_row_objects(page_index=page_index, rows=drawing_rows)
        if use_drawing_rows
        else ()
    )
    structured = build_structured_rule_sets(page_index=page_index, clauses=note_clauses)
    return ExtractedPageArtifacts(
        regions=build_page_regions(page_index=page_index, text=text, sheet_type="notes_spec", sheet_title=sheet_title),
        note_clauses=note_clauses,
        note_clause_objects=structured["note_clause_objects"],
        room_labels=extract_room_labels(text),
        equipment_labels=extract_equipment_labels(text),
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
        metadata={
            "drawing_index_notes_gate_passed": use_drawing_rows,
            "drawing_index_table_rows_detected": len(table_drawing_rows),
            "drawing_index_text_rows_detected": len(text_drawing_rows),
        },
    )
