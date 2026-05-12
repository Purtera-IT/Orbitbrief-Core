from dataclasses import replace
import re

from .common import ExtractedPageArtifacts, build_structured_rule_sets, extract_note_clauses
from .equipment_room_extractor import extract_equipment_room_sheet
from .floorplan_extractor import extract_floorplan_sheet
from .index_sheet_extractor import extract_index_sheet
from .installation_detail_extractor import extract_installation_detail_sheet
from .legend_sheet_extractor import extract_legend_sheet
from .notes_spec_extractor import extract_notes_spec_sheet
from .riser_extractor import extract_riser_sheet
from .schedule_sheet_extractor import extract_schedule_sheet
from ..models import SiteSchematicPseudoPage, SiteSchematicRegion, SiteSchematicUniversalTable


def _preferred_sheet_type_for_subregion(sheet_type: str, role: str) -> str:
    if sheet_type in {"floorplan_detail", "equipment_room_layout", "installation_detail", "rack_detail"}:
        if role == "mini_floorplan":
            return "floorplan_detail"
        if role in {"equipment_elevation"}:
            return "equipment_room_layout"
        if role in {"riser_diagram_fragment"}:
            return "riser_diagram"
        if role in {"detail_note_block", "legend_table_box", "general_notes_block"}:
            return "installation_detail"
    return sheet_type


_NOTE_CUE_RE = re.compile(r"(?i)\b(note|notes|keyed note|general note|spec|specification|requirement)\b")


def _ensure_minimum_note_clauses(
    *,
    artifacts: ExtractedPageArtifacts,
    page_index: int,
    text: str,
) -> ExtractedPageArtifacts:
    if artifacts.note_clauses:
        return artifacts
    if not _NOTE_CUE_RE.search(text or ""):
        return artifacts
    clauses = extract_note_clauses(text)
    if not clauses:
        for chunk in re.split(r"(?<=[\.;:])\s+|\n+", text or ""):
            candidate = chunk.strip()
            if 20 <= len(candidate) <= 320 and _NOTE_CUE_RE.search(candidate):
                clauses = (candidate,)
                break
    if not clauses:
        return artifacts
    structured = build_structured_rule_sets(page_index=page_index, clauses=clauses)
    return replace(
        artifacts,
        note_clauses=clauses,
        note_clause_objects=structured["note_clause_objects"],
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


def extract_by_sheet_type(
    *,
    page_index: int,
    text: str,
    sheet_type: str,
    overlay_tags: tuple[str, ...],
    sheet_title: str = "",
    regions: tuple[SiteSchematicRegion, ...] | None = None,
    pseudo_page: SiteSchematicPseudoPage | None = None,
    universal_tables: tuple[SiteSchematicUniversalTable, ...] = (),
    promoted_note_candidates: tuple[dict[str, object], ...] = (),
) -> ExtractedPageArtifacts:
    effective_text = pseudo_page.text if pseudo_page is not None else text
    effective_sheet_type = _preferred_sheet_type_for_subregion(sheet_type, pseudo_page.role) if pseudo_page is not None else sheet_type
    effective_regions = tuple(regions or ())
    pseudo_page_id = pseudo_page.pseudo_page_id if pseudo_page is not None else ""
    parent_region_id = pseudo_page.parent_region_id if pseudo_page is not None else ""
    subregion_role = pseudo_page.role if pseudo_page is not None else ""

    if sheet_type == "legend_symbol":
        artifacts = extract_legend_sheet(
            page_index=page_index,
            text=effective_text,
            overlay_tags=overlay_tags,
            sheet_title=sheet_title,
            universal_tables=universal_tables,
            promoted_note_candidates=promoted_note_candidates,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type == "notes_spec":
        artifacts = extract_notes_spec_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_title=sheet_title,
            universal_tables=universal_tables,
            promoted_note_candidates=promoted_note_candidates,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type == "schedule_sheet":
        artifacts = extract_schedule_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_title=sheet_title,
            universal_tables=universal_tables,
            promoted_note_candidates=promoted_note_candidates,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type in {"floorplan_overall", "floorplan_detail"}:
        artifacts = extract_floorplan_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_type=effective_sheet_type,
            sheet_title=sheet_title,
            regions=effective_regions or None,
            pseudo_page_id=pseudo_page_id,
            parent_region_id=parent_region_id,
            subregion_role=subregion_role,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type == "riser_diagram":
        artifacts = extract_riser_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_title=sheet_title,
            promoted_note_candidates=promoted_note_candidates,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type == "equipment_room_layout":
        artifacts = extract_equipment_room_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_title=sheet_title,
            regions=effective_regions or None,
            pseudo_page_id=pseudo_page_id,
            parent_region_id=parent_region_id,
            subregion_role=subregion_role,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    if effective_sheet_type in {"installation_detail", "rack_detail"}:
        artifacts = extract_installation_detail_sheet(
            page_index=page_index,
            text=effective_text,
            sheet_title=sheet_title,
            regions=effective_regions or None,
            pseudo_page_id=pseudo_page_id,
            parent_region_id=parent_region_id,
            subregion_role=subregion_role,
        )
        return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)
    artifacts = extract_index_sheet(page_index=page_index, text=effective_text, sheet_title=sheet_title, universal_tables=universal_tables)
    return _ensure_minimum_note_clauses(artifacts=artifacts, page_index=page_index, text=effective_text)


__all__ = [
    "ExtractedPageArtifacts",
    "extract_by_sheet_type",
    "extract_equipment_room_sheet",
    "extract_floorplan_sheet",
    "extract_index_sheet",
    "extract_installation_detail_sheet",
    "extract_legend_sheet",
    "extract_notes_spec_sheet",
    "extract_riser_sheet",
    "extract_schedule_sheet",
]
