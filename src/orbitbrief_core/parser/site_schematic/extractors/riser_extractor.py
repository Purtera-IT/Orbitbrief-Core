from __future__ import annotations

from typing import Any

from orbitbrief_core.parser.site_schematic.extractors.common import (
    ExtractedPageArtifacts,
    build_structured_rule_sets,
    extract_equipment_labels,
    extract_note_clauses,
    extract_room_labels,
)
from orbitbrief_core.parser.site_schematic.zoning.page_zones import build_page_regions


def extract_riser_sheet(
    *,
    page_index: int,
    text: str,
    sheet_title: str = "",
    promoted_note_candidates: tuple[dict[str, Any], ...] = (),
) -> ExtractedPageArtifacts:
    note_clauses = extract_note_clauses(text)
    if not note_clauses and promoted_note_candidates:
        promoted_text = tuple((row.get("text", "") or "").strip() for row in promoted_note_candidates if (row.get("text", "") or "").strip())
        note_clauses = tuple(dict.fromkeys(promoted_text))
    structured = build_structured_rule_sets(page_index=page_index, clauses=note_clauses)
    return ExtractedPageArtifacts(
        regions=build_page_regions(page_index=page_index, text=text, sheet_type="riser_diagram", sheet_title=sheet_title),
        note_clauses=note_clauses,
        note_clause_objects=structured["note_clause_objects"],
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
    )
