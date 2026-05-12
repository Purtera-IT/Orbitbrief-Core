from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
import re
from typing import Iterable, Mapping

from pypdf import PdfReader

from orbitbrief_core.parser.adapters.common import extract_path, extract_text
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.classification.overlay_type import classify_overlay_tags, compute_document_overlay_hints
from orbitbrief_core.parser.site_schematic.classification.sheet_type import (
    SheetClassification,
    classify_sheet,
)
from orbitbrief_core.parser.site_schematic.config.model_registry import load_site_schematic_model_registry
from orbitbrief_core.parser.site_schematic.extractors import ExtractedPageArtifacts, extract_by_sheet_type
from orbitbrief_core.parser.site_schematic.extractors.common import build_structured_rule_sets, extract_note_clauses
from orbitbrief_core.parser.site_schematic.graph.build_graph import build_packet_graph
from orbitbrief_core.parser.site_schematic.zoning.page_zones import (
    build_nested_detail_regions,
    build_page_regions,
    build_pseudo_pages,
    classify_subregions,
    resolve_note_scope,
)
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicAbbreviationEntry,
    SiteSchematicBundle,
    SiteSchematicCloset,
    SiteSchematicDetailRegion,
    SiteSchematicDeviceInstance,
    SiteSchematicDrawingIndexRow,
    SiteSchematicGroundedSymbol,
    SiteSchematicLegendEntry,
    SiteSchematicLegendGroundingEntry,
    SiteSchematicMeasurementCandidate,
    SiteSchematicNoteClause,
    SiteSchematicObservation,
    SiteSchematicOutletInstance,
    SiteSchematicPacketV0V1Summary,
    SiteSchematicPacketV2HardpageSummary,
    SiteSchematicPacketV2EnforcementSummary,
    SiteSchematicPacketV2FamilyCoverageSummary,
    SiteSchematicPacketV2QualitySummary,
    SiteSchematicPacketV2Summary,
    SiteSchematicPacketV2TruthAuditSummary,
    SiteSchematicPage,
    SiteSchematicPageSection,
    SiteSchematicPageModalityDecision,
    SiteSchematicPageObservation,
    SiteSchematicPseudoPage,
    SiteSchematicRack,
    SiteSchematicRegion,
    SiteSchematicRiserEdge,
    SiteSchematicRoom,
    SiteSchematicScopedNoteLink,
    SiteSchematicSubregion,
    SiteSchematicSymbolCandidateGroup,
    SiteSchematicSymbolCandidateInput,
    SiteSchematicSymbolInstance,
    SiteSchematicSymbolLink,
    SiteSchematicSymbolResolutionOutcome,
    SiteSchematicTopologyEndpoint,
    SiteSchematicTopologyRelation,
    SiteSchematicTopologySegment,
    SiteSchematicVectorPrimitive,
    SiteSchematicVectorPrimitiveGraph,
    SiteSchematicVectorPrimitiveValidation,
)
from orbitbrief_core.parser.site_schematic.layout_sections import detect_page_sections_from_pdf
from orbitbrief_core.parser.site_schematic.modality_calibration import calibrate_modality_decision
from orbitbrief_core.parser.site_schematic.modality_zero_guard import detect_suspicious_zero_primitive_page
from orbitbrief_core.parser.site_schematic.observations import build_site_schematic_page_observations
from orbitbrief_core.parser.site_schematic.packet_v0_v1_quality import summarize_packet_v0_v1
from orbitbrief_core.parser.site_schematic.family_coverage_truth import compute_family_coverage_truth
from orbitbrief_core.parser.site_schematic.family_coverage_enforcement import compute_family_coverage
from orbitbrief_core.parser.site_schematic.grounded_yield_metrics import compute_grounded_yield_metrics
from orbitbrief_core.parser.site_schematic.grounding_truth_audit import audit_packet_truth_signals
from orbitbrief_core.parser.site_schematic.hardpage_requirement_repair import derive_required_hardpages
from orbitbrief_core.parser.site_schematic.hardpage_gate_enforcement import enforce_hardpage_truth
from orbitbrief_core.parser.site_schematic.hardpage_semantic_gate_v2_5 import enforce_v2_5_hardpage_gate
from orbitbrief_core.parser.site_schematic.hardpage_truth_enforcer import enforce_nonempty_required_hardpages
from orbitbrief_core.parser.site_schematic.legend_grounding_models import LegendGroundingEntry
from orbitbrief_core.parser.site_schematic.packet_hardpage_semantics import build_packet_hardpage_summary
from orbitbrief_core.parser.site_schematic.hardpage_requirement_registry import derive_required_hardpage_types
from orbitbrief_core.parser.site_schematic.grounding_resolver import resolve_grounded_symbols
from orbitbrief_core.parser.site_schematic.primitive_dedup import dedup_vector_primitives
from orbitbrief_core.parser.site_schematic.primitive_density_audit import audit_primitive_density
from orbitbrief_core.parser.site_schematic.primitive_validation import validate_vector_primitive
from orbitbrief_core.parser.site_schematic.semantic_mapper import build_legend_grounding_dictionary
from orbitbrief_core.parser.site_schematic.leader_dimension_quality import (
    score_dimension_semantic_quality,
    score_leader_semantic_quality,
)
from orbitbrief_core.parser.site_schematic.symbol_candidate_grouping import group_symbol_candidates_from_primitives
from orbitbrief_core.parser.site_schematic.sample_row_audit import select_grounding_sample_rows
from orbitbrief_core.parser.site_schematic.packet_expected_family_deriver import derive_expected_families_from_packet_local_text
from orbitbrief_core.parser.site_schematic.observation_escalation_policy import choose_page_escalation_policy
from orbitbrief_core.parser.site_schematic.page_modality_router import classify_page_modality
from orbitbrief_core.parser.site_schematic.final_text_tail_registry import lookup_tail_note_gap_profile
from orbitbrief_core.parser.site_schematic.note_clause_promoter import promote_note_clauses_from_blocks
from orbitbrief_core.parser.site_schematic.reasoning import build_bounded_graph_reasoning, build_reasoning_summaries
from orbitbrief_core.parser.site_schematic.region_bbox_completion import complete_region_bbox_from_children
from orbitbrief_core.parser.site_schematic.structure_graph import build_page_structure_graph
from orbitbrief_core.parser.site_schematic.vector_measurement import build_measurement_candidates_from_vector_graph
from orbitbrief_core.parser.site_schematic.vector_primitive_graph import build_vector_primitive_graph
from orbitbrief_core.parser.site_schematic.vector_primitives import (
    VectorPrimitive,
    extract_vector_primitives_from_vector_items,
)
from orbitbrief_core.parser.site_schematic.universal_table_spine import (
    attach_semantic_lineage,
    build_universal_tables_for_page,
)
from orbitbrief_core.parser.site_schematic.topology_extract import build_topology_for_page
from orbitbrief_core.parser.site_schematic.symbols.detector import (
    detect_primitive_symbols,
    map_symbol_instances_to_primitive_detections,
    materialize_symbol_instances_from_detections,
)
from orbitbrief_core.parser.site_schematic.symbols.model_output_adapter import load_model_primitive_detections
from orbitbrief_core.parser.site_schematic.symbols.linker import (
    build_symbol_resolution_outcomes,
    link_symbol_instances,
    strengthen_symbol_links_with_topology,
)
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import (
    get_detector_profile,
    profile_threshold_delta,
    select_profile_for_context,
)

_PAGE_MARKER_RE = re.compile(r"(?is)<PARSED TEXT FOR PAGE:\s*(\d+)\s*/\s*(\d+)>\s*(.*?)(?=<PARSED TEXT FOR PAGE:|\Z)")
_CLOSET_RE = re.compile(r"(?i)\b(?:MDF|IDF|TR|TEL(?:ECOMM)?\s+CLOSET|A/V\s+CLOSET|AV\s+ROOM)\b[^\n]{0,48}")
_RACK_RE = re.compile(r"(?i)\b(?:RACK(?:S)?|CABINET(?:S)?|PATCH\s+PANEL|LADDER\s+RACK|BUSBAR)\b[^\n]{0,60}")
_ROUTED_TO_RE = re.compile(r"(?i)\b(?:run|route|routed|homerun)\b[^.\n]{0,80}\b(?:to|toward)\b[^.\n]{0,120}")
_MEDIUM_RE = re.compile(r"(?i)\b(?:CAT[- ]?\d+[a-z]?|RG-?\d+|fiber|singlemode|multimode|copper|OSP)\b")
_PAGE_LEVEL_NOTE_CUES = ("note", "notes", "keyed note", "general note", "spec", "requirement")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe_text(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        cleaned = _clean(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(cleaned)
    return tuple(rows)


def _dedupe_limited(items: Iterable[str], *, limit: int = 8) -> tuple[str, ...]:
    rows = _dedupe_text(items)
    return rows[: max(0, limit)]


def _ensure_page_level_note_clause_presence(
    *,
    packet_id: str,
    page_index: int,
    sheet_type: str,
    page_text: str,
    artifacts: ExtractedPageArtifacts,
) -> ExtractedPageArtifacts:
    if artifacts.note_clauses:
        return artifacts
    lowered = (page_text or "").lower()
    if not lowered or not any(token in lowered for token in _PAGE_LEVEL_NOTE_CUES):
        return artifacts
    clauses = extract_note_clauses(page_text)
    tail_profile = lookup_tail_note_gap_profile(packet_id, page_index, sheet_type)
    if not clauses:
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        candidate = next(
            (
                line
                for line in lines
                if 16 <= len(line) <= 320 and any(token in line.lower() for token in _PAGE_LEVEL_NOTE_CUES)
            ),
            "",
        )
        if candidate:
            clauses = (candidate,)
    if not clauses and tail_profile:
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        numbered = tuple(
            line
            for line in lines
            if re.match(r"^\s*\d+\s+[A-Za-z].{8,}$", line)
        )
        if numbered:
            clauses = numbered[:8]
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


def _infer_page_width(page_observation: SiteSchematicPageObservation | None) -> float:
    if page_observation is None or not page_observation.layout_blocks:
        return 1000.0
    max_x = 0.0
    min_x = float("inf")
    for block in page_observation.layout_blocks:
        if block.bbox is None:
            continue
        min_x = min(min_x, float(block.bbox[0]))
        max_x = max(max_x, float(block.bbox[2]))
    if min_x == float("inf") or max_x <= min_x:
        return 1000.0
    return max(200.0, max_x - min_x)


def _build_symbol_candidate_inputs_for_page(
    *,
    artifact_id: str,
    page_index: int,
    sheet_type: str,
    sheet_number: str,
    sheet_title: str,
    page_observation: SiteSchematicPageObservation | None,
    regions: tuple[SiteSchematicRegion, ...],
    detail_regions: tuple[SiteSchematicDetailRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...],
    scoped_note_links: tuple[SiteSchematicScopedNoteLink, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
    room_labels: tuple[str, ...],
) -> tuple[SiteSchematicSymbolCandidateInput, ...]:
    detail_by_id = {row.detail_region_id: row for row in detail_regions}
    subregion_by_id = {row.subregion_id: row for row in subregions}
    region_by_id = {row.region_id: row for row in regions}
    provider = page_observation.provider if page_observation else "deterministic"
    source_mode = page_observation.source_mode if page_observation else "decomposition_heuristic"
    page_note_pool = [row.note_text for row in scoped_note_links if row.scope_level == "page_global"]
    legend_ids = _dedupe_limited((row.entry_id for row in legend_entries), limit=8)
    legend_texts = _dedupe_limited((f"{row.label} {row.description}".strip() for row in legend_entries), limit=8)
    nearby_abbreviations = _dedupe_limited((f"{row.token}={row.meaning}" for row in abbreviations), limit=8)
    nearby_closets = _dedupe_limited((row for row in room_labels if _CLOSET_RE.search(row)), limit=6)
    rows: list[SiteSchematicSymbolCandidateInput] = []
    if pseudo_pages:
        for idx, pseudo in enumerate(pseudo_pages, start=1):
            subregion = subregion_by_id.get(pseudo.subregion_id)
            detail = detail_by_id.get(pseudo.detail_region_id or (subregion.detail_region_id if subregion else ""))
            region = region_by_id.get(pseudo.parent_region_id or (subregion.parent_region_id if subregion else ""))
            local_notes = list(page_note_pool)
            local_notes.extend(
                row.note_text
                for row in scoped_note_links
                if pseudo.pseudo_page_id in row.scope_targets
                or row.pseudo_page_id == pseudo.pseudo_page_id
                or (row.parent_region_id and row.parent_region_id == pseudo.parent_region_id)
            )
            decomp_confidence = sum(
                (
                    pseudo.confidence,
                    subregion.confidence if subregion else 0.0,
                    detail.confidence if detail else 0.0,
                    region.confidence if region else 0.0,
                )
            ) / (1 + int(subregion is not None) + int(detail is not None) + int(region is not None))
            rows.append(
                SiteSchematicSymbolCandidateInput(
                    candidate_id=f"sym_input:p{page_index}:pp:{idx}",
                    artifact_id=artifact_id,
                    page_index=page_index,
                    sheet_type=sheet_type,
                    sheet_number=sheet_number,
                    sheet_title=sheet_title,
                    region_id=region.region_id if region else pseudo.parent_region_id,
                    detail_region_id=detail.detail_region_id if detail else pseudo.detail_region_id,
                    subregion_id=subregion.subregion_id if subregion else pseudo.subregion_id,
                    pseudo_page_id=pseudo.pseudo_page_id,
                    bbox=pseudo.bbox,
                    source_mode=pseudo.source_mode or source_mode,
                    provider=provider,
                    decomposition_confidence=round(decomp_confidence, 4),
                    local_text_context=_clean(pseudo.text)[:800],
                    nearby_note_clauses=_dedupe_limited(local_notes, limit=10),
                    nearby_legend_entry_ids=legend_ids,
                    nearby_legend_texts=legend_texts,
                    nearby_abbreviations=nearby_abbreviations,
                    nearby_room_labels=_dedupe_limited(room_labels, limit=8),
                    nearby_closet_labels=nearby_closets,
                    metadata={"contract_version": "symbol_input_v1", "anchor_level": "pseudo_page"},
                )
            )
    if rows:
        return tuple(rows)
    for idx, subregion in enumerate(subregions, start=1):
        detail = detail_by_id.get(subregion.detail_region_id)
        region = region_by_id.get(subregion.parent_region_id)
        local_notes = list(page_note_pool)
        local_notes.extend(
            row.note_text
            for row in scoped_note_links
            if row.parent_region_id == subregion.parent_region_id
            or subregion.subregion_id in row.scope_targets
        )
        decomp_confidence = sum(
            (
                subregion.confidence,
                detail.confidence if detail else 0.0,
                region.confidence if region else 0.0,
            )
        ) / (1 + int(detail is not None) + int(region is not None))
        rows.append(
            SiteSchematicSymbolCandidateInput(
                candidate_id=f"sym_input:p{page_index}:sr:{idx}",
                artifact_id=artifact_id,
                page_index=page_index,
                sheet_type=sheet_type,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                region_id=region.region_id if region else subregion.parent_region_id,
                detail_region_id=detail.detail_region_id if detail else subregion.detail_region_id,
                subregion_id=subregion.subregion_id,
                bbox=subregion.bbox,
                source_mode=subregion.source_mode or source_mode,
                provider=provider,
                decomposition_confidence=round(decomp_confidence, 4),
                local_text_context=_clean(subregion.text)[:800],
                nearby_note_clauses=_dedupe_limited(local_notes, limit=10),
                nearby_legend_entry_ids=legend_ids,
                nearby_legend_texts=legend_texts,
                nearby_abbreviations=nearby_abbreviations,
                nearby_room_labels=_dedupe_limited(room_labels, limit=8),
                nearby_closet_labels=nearby_closets,
                metadata={"contract_version": "symbol_input_v1", "anchor_level": "subregion"},
            )
        )
    return tuple(rows)


def _extract_page_texts_from_pdf(path: Path) -> list[str]:
    try:
        import fitz  # type: ignore

        document = fitz.open(path)
        rows = [page.get_text("text") or "" for page in document]
        if any(row.strip() for row in rows):
            return rows
    except Exception:
        pass
    reader = PdfReader(str(path))
    rows: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        rows.append(text)
    return rows


def _extract_page_texts_from_text(text: str) -> list[str]:
    rows: list[str] = []
    for match in _PAGE_MARKER_RE.finditer(text or ""):
        rows.append(match.group(3).strip())
    if rows:
        return rows
    if "\f" in (text or ""):
        return [chunk.strip() for chunk in text.split("\f") if chunk.strip()]
    return [text.strip()] if (text or "").strip() else []


def extract_page_texts(router_input: RouterInput) -> list[str]:
    path = extract_path(router_input)
    if path and path.suffix.lower() == ".pdf":
        try:
            return _extract_page_texts_from_pdf(path)
        except Exception:
            pass
    if isinstance(router_input.metadata, Mapping):
        page_texts = router_input.metadata.get("page_texts")
        if isinstance(page_texts, list):
            cleaned = [str(item).strip() for item in page_texts if str(item).strip()]
            if cleaned:
                return cleaned
    text = extract_text(router_input, prefer_full_text=True)
    return _extract_page_texts_from_text(text)


def classify_sheet_type(text: str) -> str:
    return classify_sheet(text).sheet_type


def _zone_names_from_regions(regions: tuple[SiteSchematicRegion, ...]) -> tuple[str, ...]:
    mapping = {
        "title_block": "title_block_zone",
        "revision_block": "revision_zone",
        "legend_block": "legend_zone",
        "abbreviation_block": "abbreviation_zone",
        "notes_spec_block": "note_spec_zone",
        "schedule_table_block": "schedule_table_zone",
        "plan_body_block": "plan_body_zone",
        "detail_block": "detail_zone",
        "border_noise_block": "border_noise_zone",
    }
    values: list[str] = []
    for region in regions:
        values.append(mapping.get(region.kind, f"{region.kind}_zone"))
    return tuple(dict.fromkeys(values))


def _infer_room_kind(label: str) -> str:
    lowered = label.lower()
    if "mdf" in lowered:
        return "mdf"
    if "idf" in lowered:
        return "idf"
    if "tr" in lowered or "closet" in lowered:
        return "telecom_closet"
    if "av" in lowered:
        return "av_room"
    return "room"


def _build_room_objects(*, page_index: int, labels: tuple[str, ...]) -> tuple[SiteSchematicRoom, ...]:
    rows: list[SiteSchematicRoom] = []
    for idx, label in enumerate(labels, start=1):
        rows.append(
            SiteSchematicRoom(
                room_id=f"room:p{page_index}:{idx}",
                page_index=page_index,
                label=label,
                room_kind=_infer_room_kind(label),
                confidence=0.78,
            )
        )
    return tuple(rows)


def _build_closets(*, page_index: int, labels: tuple[str, ...]) -> tuple[SiteSchematicCloset, ...]:
    rows: list[SiteSchematicCloset] = []
    idx = 0
    for label in labels:
        if not _CLOSET_RE.search(label):
            continue
        idx += 1
        rows.append(
            SiteSchematicCloset(
                closet_id=f"closet:p{page_index}:{idx}",
                page_index=page_index,
                label=label,
                closet_kind=_infer_room_kind(label),
                confidence=0.8,
            )
        )
    return tuple(rows)


def _build_racks(*, page_index: int, text: str) -> tuple[SiteSchematicRack, ...]:
    rows: list[SiteSchematicRack] = []
    seen: set[str] = set()
    for idx, match in enumerate(_RACK_RE.finditer(text), start=1):
        value = _clean(match.group(0))
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            SiteSchematicRack(
                rack_id=f"rack:p{page_index}:{idx}",
                page_index=page_index,
                label=value,
                confidence=0.73,
            )
        )
    return tuple(rows)


def _build_riser_edges(*, page_index: int, text: str) -> tuple[SiteSchematicRiserEdge, ...]:
    rows: list[SiteSchematicRiserEdge] = []
    for idx, match in enumerate(_ROUTED_TO_RE.finditer(text), start=1):
        row = _clean(match.group(0))
        medium_match = _MEDIUM_RE.search(row)
        rows.append(
            SiteSchematicRiserEdge(
                edge_id=f"riser_edge:p{page_index}:{idx}",
                page_index=page_index,
                source_label=f"sheet_{page_index}",
                target_label=row,
                medium=_clean(medium_match.group(0)) if medium_match else "",
                confidence=0.66,
            )
        )
    return tuple(rows)


def _build_topology_segments(*, page_index: int, text: str) -> tuple[SiteSchematicTopologySegment, ...]:
    rows: list[SiteSchematicTopologySegment] = []
    for idx, match in enumerate(_ROUTED_TO_RE.finditer(text), start=1):
        row = _clean(match.group(0))
        rows.append(
            SiteSchematicTopologySegment(
                segment_id=f"topology:p{page_index}:{idx}",
                page_index=page_index,
                text=row,
                confidence=0.66,
            )
        )
    return tuple(rows)


def _build_device_and_outlet_instances(
    *,
    page_index: int,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
) -> tuple[tuple[SiteSchematicDeviceInstance, ...], tuple[SiteSchematicOutletInstance, ...]]:
    devices: list[SiteSchematicDeviceInstance] = []
    outlets: list[SiteSchematicOutletInstance] = []
    for idx, symbol in enumerate(symbol_instances, start=1):
        normalized = symbol.token.upper()
        if normalized in {"AP", "WAP", "CCTV", "TV", "POS-T", "POS-P", "WN", "ZN"}:
            devices.append(
                SiteSchematicDeviceInstance(
                    device_id=f"device:p{page_index}:{idx}",
                    page_index=page_index,
                    token=normalized,
                    device_type=symbol.primitive_kind,
                    text=symbol.text,
                    room_label=symbol.room_label,
                    confidence=symbol.confidence,
                    status="inferred",
                    metadata={"source_instance_id": symbol.instance_id},
                )
            )
        else:
            outlets.append(
                SiteSchematicOutletInstance(
                    outlet_id=f"outlet:p{page_index}:{idx}",
                    page_index=page_index,
                    outlet_type=normalized,
                    text=symbol.text,
                    room_label=symbol.room_label,
                    confidence=symbol.confidence,
                    status="inferred",
                    metadata={"source_instance_id": symbol.instance_id},
                )
            )
    return tuple(devices), tuple(outlets)


def _merge_symbol_instances(
    *,
    model_rows: tuple[SiteSchematicSymbolInstance, ...],
    heuristic_rows: tuple[SiteSchematicSymbolInstance, ...],
) -> tuple[SiteSchematicSymbolInstance, ...]:
    merged: list[SiteSchematicSymbolInstance] = []
    seen: set[tuple[str, tuple[float, float, float, float] | None]] = set()

    def _bbox_key(value: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        return tuple(round(float(v), 2) for v in value)

    for row in (*model_rows, *heuristic_rows):
        key = (row.token.upper(), _bbox_key(row.bbox))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return tuple(merged)


def _apply_region_profile_metadata(
    *,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    sheet_type: str,
    regions: tuple[SiteSchematicRegion, ...],
    detail_regions: tuple[SiteSchematicDetailRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...],
) -> tuple[SiteSchematicSymbolInstance, ...]:
    if not symbol_instances:
        return ()
    region_kind_by_id = {row.region_id: row.kind for row in regions}
    detail_kind_by_id = {row.detail_region_id: row.kind for row in detail_regions}
    subregion_role_by_id = {row.subregion_id: row.role for row in subregions}
    pseudo_role_by_id = {row.pseudo_page_id: row.role for row in pseudo_pages}
    updated: list[SiteSchematicSymbolInstance] = []
    for symbol in symbol_instances:
        metadata = dict(symbol.metadata or {})
        detector_class_id = str(metadata.get("detector_class_id", "")).strip()
        detail_region_id = str(metadata.get("detail_region_id", "")).strip()
        subregion_id = str(metadata.get("subregion_id", "")).strip()
        pseudo_page_id = str(symbol.pseudo_page_id or metadata.get("pseudo_page_id", "")).strip()
        region_kind = str(metadata.get("region_kind", "")).strip() or region_kind_by_id.get(symbol.region_id, "")
        detail_kind = str(metadata.get("detail_kind", "")).strip() or detail_kind_by_id.get(detail_region_id, "")
        subregion_role = str(metadata.get("subregion_role", "")).strip() or subregion_role_by_id.get(subregion_id, "")
        pseudo_role = str(metadata.get("pseudo_page_role", "")).strip() or pseudo_role_by_id.get(pseudo_page_id, "")
        profile_id, profile_reasons = select_profile_for_context(
            sheet_type=sheet_type,
            region_kind=region_kind,
            detail_kind=detail_kind,
            subregion_role=subregion_role,
            pseudo_role=pseudo_role,
            local_text=f"{symbol.text} {symbol.room_label}",
        )
        profile = get_detector_profile(profile_id)
        metadata.update(
            {
                "sheet_type": sheet_type,
                "region_kind": region_kind,
                "detail_kind": detail_kind,
                "subregion_role": subregion_role,
                "pseudo_page_role": pseudo_role,
                "detector_profile_id": profile_id,
                "detector_profile_reasons": list(profile_reasons),
                "detector_profile_favored_classes": sorted(set(profile.get("favored_classes", set()))),
                "detector_profile_suppressed_classes": sorted(set(profile.get("suppressed_classes", set()))),
                "detector_profile_threshold_delta": profile_threshold_delta(profile_id, detector_class_id) if detector_class_id else 0.0,
            }
        )
        updated.append(replace(symbol, metadata=metadata, pseudo_page_id=pseudo_page_id))
    return tuple(updated)


def _emit_observations(
    *,
    page_index: int,
    sheet_type: str,
    overlay_tags: tuple[str, ...],
    regions: tuple[SiteSchematicRegion, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
    outlet_type_definitions: tuple,
    note_clauses: tuple[str, ...],
    room_labels: tuple[str, ...],
    equipment_labels: tuple[str, ...],
    drawing_index_rows: tuple[str, ...],
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    symbol_links: tuple[SiteSchematicSymbolLink, ...],
    counter: Counter[str],
) -> list[SiteSchematicObservation]:
    observations: list[SiteSchematicObservation] = []
    region_by_kind: dict[str, SiteSchematicRegion] = {region.kind: region for region in regions}

    def emit(kind: str, text: str, *, region_kind: str, confidence: float, metadata: Mapping[str, object] | None = None) -> None:
        counter[kind] += 1
        region = region_by_kind.get(region_kind) or next(iter(regions), None)
        observations.append(
            SiteSchematicObservation(
                observation_id=f"p{page_index}:{kind}:{counter[kind]}",
                page_index=page_index,
                sheet_type=sheet_type,
                zone=f"{region_kind}_zone",
                overlay_tags=overlay_tags,
                kind=kind,
                text=text,
                confidence=confidence,
                region_id=region.region_id if region else "",
                bbox=region.bbox if region else None,
                source_mode=region.source_mode if region else "text_heuristic",
                metadata=dict(metadata or {}),
            )
        )

    for entry in legend_entries:
        emit("legend_entry", entry.description, region_kind="legend_block", confidence=entry.confidence, metadata={"entry_id": entry.entry_id, "label": entry.label, "primitive_kind": entry.primitive_kind})
    for entry in abbreviations:
        emit("abbreviation_entry", f"{entry.token} = {entry.meaning}", region_kind="abbreviation_block", confidence=entry.confidence, metadata={"entry_id": entry.entry_id, "category": entry.category})
    for entry in outlet_type_definitions:
        emit(
            "outlet_type_definition",
            entry.label,
            region_kind="legend_block",
            confidence=entry.confidence,
            metadata={
                "definition_id": entry.definition_id,
                "mounting": entry.mounting,
                "closet_termination": entry.closet_termination,
                "status": entry.status,
            },
        )
    for row in note_clauses:
        emit("note_clause", row, region_kind="notes_spec_block", confidence=0.72)
    for row in room_labels:
        emit("room_label", row, region_kind="plan_body_block", confidence=0.79)
    for row in equipment_labels:
        emit("equipment_label", row, region_kind="plan_body_block", confidence=0.76)
    for row in drawing_index_rows:
        emit("drawing_index_row", row, region_kind="schedule_table_block", confidence=0.7)
    for symbol in symbol_instances:
        counter["symbol_instance"] += 1
        observations.append(
            SiteSchematicObservation(
                observation_id=f"p{page_index}:symbol_instance:{counter['symbol_instance']}",
                page_index=page_index,
                sheet_type=sheet_type,
                zone="plan_body_zone",
                overlay_tags=overlay_tags,
                kind="symbol_instance",
                text=symbol.token,
                confidence=symbol.confidence,
                region_id=symbol.region_id,
                bbox=symbol.bbox,
                source_mode=symbol.source_mode,
                metadata={"instance_id": symbol.instance_id, "primitive_kind": symbol.primitive_kind},
            )
        )
    for link in symbol_links:
        counter["symbol_link"] += 1
        observations.append(
            SiteSchematicObservation(
                observation_id=f"p{page_index}:symbol_link:{counter['symbol_link']}",
                page_index=page_index,
                sheet_type=sheet_type,
                zone="plan_body_zone",
                overlay_tags=overlay_tags,
                kind="symbol_link",
                text=f"{link.symbol_token} -> {link.legend_label or link.status}",
                confidence=link.confidence,
                source_mode="linker_heuristic",
                metadata={"link_id": link.link_id, "status": link.status, "legend_entry_id": link.legend_entry_id},
            )
        )
    return observations


def _merge_subregion_artifacts(*, page_index: int, rows: tuple[ExtractedPageArtifacts, ...]) -> ExtractedPageArtifacts:
    merged_metadata: dict[str, object] = {"merge_source": "subregion_dispatch", "page_index": page_index, "subregion_count": len(rows)}
    return ExtractedPageArtifacts(
        regions=tuple(region for row in rows for region in row.regions),
        detail_regions=tuple(region for row in rows for region in row.detail_regions),
        subregions=tuple(region for row in rows for region in row.subregions),
        pseudo_pages=tuple(page for row in rows for page in row.pseudo_pages),
        scoped_note_links=tuple(link for row in rows for link in row.scoped_note_links),
        legend_entries=tuple(item for row in rows for item in row.legend_entries),
        abbreviations=tuple(item for row in rows for item in row.abbreviations),
        outlet_type_definitions=tuple(item for row in rows for item in row.outlet_type_definitions),
        note_clauses=_dedupe_text([item for row in rows for item in row.note_clauses]),
        note_clause_objects=tuple(item for row in rows for item in row.note_clause_objects),
        room_labels=_dedupe_text([item for row in rows for item in row.room_labels]),
        equipment_labels=_dedupe_text([item for row in rows for item in row.equipment_labels]),
        drawing_index_rows=_dedupe_text([item for row in rows for item in row.drawing_index_rows]),
        drawing_index_row_objects=tuple(item for row in rows for item in row.drawing_index_row_objects),
        mounting_rules=tuple(item for row in rows for item in row.mounting_rules),
        termination_rules=tuple(item for row in rows for item in row.termination_rules),
        color_conventions=tuple(item for row in rows for item in row.color_conventions),
        environmental_requirements=tuple(item for row in rows for item in row.environmental_requirements),
        grounding_requirements=tuple(item for row in rows for item in row.grounding_requirements),
        testing_requirements=tuple(item for row in rows for item in row.testing_requirements),
        labeling_requirements=tuple(item for row in rows for item in row.labeling_requirements),
        responsibility_assignments=tuple(item for row in rows for item in row.responsibility_assignments),
        cable_rules=tuple(item for row in rows for item in row.cable_rules),
        pathway_rules=tuple(item for row in rows for item in row.pathway_rules),
        service_loop_requirements=tuple(item for row in rows for item in row.service_loop_requirements),
        symbol_instances=tuple(item for row in rows for item in row.symbol_instances),
        symbol_links=tuple(item for row in rows for item in row.symbol_links),
        metadata=merged_metadata,
    )


def _apply_note_scope(
    *,
    note_clause_objects: tuple[SiteSchematicNoteClause, ...],
    scoped_note_links: tuple[SiteSchematicScopedNoteLink, ...],
) -> tuple[SiteSchematicNoteClause, ...]:
    link_by_text = {row.note_text.lower(): row for row in scoped_note_links}
    rows: list[SiteSchematicNoteClause] = []
    for clause in note_clause_objects:
        scope = link_by_text.get(clause.text.lower())
        if scope is None:
            rows.append(clause)
            continue
        rows.append(
            SiteSchematicNoteClause(
                clause_id=clause.clause_id,
                page_index=clause.page_index,
                text=clause.text,
                clause_type=clause.clause_type,
                confidence=clause.confidence,
                status=clause.status,
                scope_level=scope.scope_level,
                scope_targets=scope.scope_targets,
                parent_region_id=scope.parent_region_id or clause.parent_region_id,
                pseudo_page_id=scope.pseudo_page_id or clause.pseudo_page_id,
                bbox=clause.bbox,
                source_mode=clause.source_mode,
                metadata={**dict(clause.metadata), "scope_status": scope.status},
            )
        )
    return tuple(rows)


_SECTION_HEADING_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9/&\-\s]{3,}$")


def _looks_like_section_heading(text: str) -> bool:
    cleaned = " ".join((text or "").strip().split())
    if len(cleaned) < 4 or len(cleaned) > 120:
        return False
    if any(ch.islower() for ch in cleaned):
        return False
    word_count = len(cleaned.split())
    # Avoid treating full sentence fragments as headings.
    if word_count > 8:
        return False
    if not _SECTION_HEADING_TOKEN_RE.match(cleaned):
        return False
    has_prefix_token = bool(re.match(r"^[A-Z]{1,3}[\).:-]?\s+", cleaned))
    heading_keyword = any(
        keyword in cleaned
        for keyword in (
            "SCOPE",
            "GUIDELINES",
            "NOTES",
            "REQUIREMENTS",
            "DOCUMENTATION",
            "OVERVIEW",
            "DRAWING INDEX",
        )
    )
    if has_prefix_token and word_count <= 6:
        return True
    if heading_keyword and word_count <= 5 and " SHALL " not in cleaned and " ARE " not in cleaned:
        return True
    return False


def _group_note_clauses_into_sections(
    *,
    note_clause_objects: tuple[SiteSchematicNoteClause, ...],
) -> tuple[SiteSchematicNoteClause, ...]:
    state_by_scope: dict[tuple[int, str], dict[str, object]] = {}
    grouped: list[SiteSchematicNoteClause] = []
    for clause in note_clause_objects:
        scope_key = (clause.page_index, clause.pseudo_page_id or "none")
        state = state_by_scope.setdefault(
            scope_key,
            {
                "section_idx": 0,
                "section_title": "",
                "section_clause_seq": 0,
            },
        )
        text = (clause.text or "").strip()
        is_heading = _looks_like_section_heading(text)
        if is_heading:
            state["section_idx"] = int(state["section_idx"]) + 1
            state["section_title"] = text
            state["section_clause_seq"] = 0
        state["section_clause_seq"] = int(state["section_clause_seq"]) + 1
        section_idx = int(state["section_idx"])
        section_title = str(state["section_title"] or "")
        section_group_id = f"section:p{clause.page_index}:{clause.pseudo_page_id or 'none'}:{section_idx:03d}"
        grouped.append(
            SiteSchematicNoteClause(
                clause_id=clause.clause_id,
                page_index=clause.page_index,
                text=clause.text,
                clause_type=clause.clause_type,
                confidence=clause.confidence,
                status=clause.status,
                scope_level=clause.scope_level,
                scope_targets=clause.scope_targets,
                parent_region_id=clause.parent_region_id,
                pseudo_page_id=clause.pseudo_page_id,
                bbox=clause.bbox,
                source_mode=clause.source_mode,
                metadata={
                    **dict(clause.metadata),
                    "section_group_id": section_group_id,
                    "section_group_title": section_title,
                    "section_group_index": section_idx,
                    "section_clause_seq": int(state["section_clause_seq"]),
                    "section_is_heading": is_heading,
                },
            )
        )
    return tuple(grouped)


def _derive_page_sections_from_note_groups(
    *,
    page_index: int,
    note_clause_objects: tuple[SiteSchematicNoteClause, ...],
) -> tuple[SiteSchematicPageSection, ...]:
    group_rows: dict[str, list[SiteSchematicNoteClause]] = {}
    for clause in note_clause_objects:
        if clause.page_index != page_index:
            continue
        metadata = dict(clause.metadata or {})
        title = str(metadata.get("section_group_title", "")).strip()
        if not title:
            continue
        group_rows.setdefault(title, []).append(clause)
    out: list[SiteSchematicPageSection] = []
    for idx, title in enumerate(sorted(group_rows.keys()), start=1):
        clauses = group_rows[title]
        ordered_lines = tuple(row.text for row in clauses if row.text)
        if not ordered_lines:
            continue
        confidence = round(min(0.9, 0.62 + min(0.22, len(ordered_lines) / 180.0)), 3)
        out.append(
            SiteSchematicPageSection(
                section_id=f"section:p{page_index}:note_group:{idx:03d}",
                page_index=page_index,
                order_index=idx,
                section_title=title,
                bbox=None,
                ordered_lines=ordered_lines,
                confidence=confidence,
                metadata={
                    "detector": "note_group_fallback",
                    "line_count": len(ordered_lines),
                    "box_indicator": True,
                    "box_role": "notes_group",
                },
            )
        )
    return tuple(out)


def _drawing_index_page_section_from_rows(
    *,
    page_index: int,
    drawing_rows: tuple[SiteSchematicDrawingIndexRow, ...],
) -> SiteSchematicPageSection | None:
    page_rows = [row for row in drawing_rows if row.page_index == page_index and row.sheet_number and row.sheet_title]
    if len(page_rows) < 2:
        return None
    ordered_lines = tuple(f"{row.sheet_number} {row.sheet_title}".strip() for row in page_rows)
    confidence = round(sum(float(row.confidence) for row in page_rows) / max(1, len(page_rows)), 3)
    return SiteSchematicPageSection(
        section_id=f"section:p{page_index}:drawing_index_rows",
        page_index=page_index,
        order_index=0,
        section_title="DRAWING INDEX",
        bbox=None,
        ordered_lines=ordered_lines,
        confidence=max(0.7, min(0.95, confidence)),
        metadata={"detector": "drawing_index_rows", "box_indicator": True, "box_role": "drawing_index"},
    )


def _merge_page_sections(
    *,
    page_index: int,
    primary: list[SiteSchematicPageSection],
    extras: tuple[SiteSchematicPageSection, ...],
    drawing_index_section: SiteSchematicPageSection | None,
) -> list[SiteSchematicPageSection]:
    merged: list[SiteSchematicPageSection] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in [*primary, *extras]:
        if row.page_index != page_index:
            continue
        key = (row.section_title.strip().upper(), str(dict(row.metadata).get("detector", "")))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(row)
    if drawing_index_section is not None:
        if not any("DRAWING INDEX" == row.section_title.strip().upper() for row in merged):
            merged.append(drawing_index_section)
    alpha_sections = [row for row in merged if str(dict(row.metadata).get("box_role", "")) == "alpha_index_grid"]
    if len(alpha_sections) > 1:
        letters: set[str] = set()
        lines: list[str] = []
        confidences: list[float] = []
        xs0: list[float] = []
        ys0: list[float] = []
        xs1: list[float] = []
        ys1: list[float] = []
        for row in alpha_sections:
            letters.update(re.findall(r"[A-Z]", row.section_title.upper()))
            lines.extend(list(row.ordered_lines))
            confidences.append(float(row.confidence))
            if row.bbox is not None:
                xs0.append(float(row.bbox[0]))
                ys0.append(float(row.bbox[1]))
                xs1.append(float(row.bbox[2]))
                ys1.append(float(row.bbox[3]))
        merged = [row for row in merged if str(dict(row.metadata).get("box_role", "")) != "alpha_index_grid"]
        if letters:
            ordered_letters = sorted(letters)
            title = f"{ordered_letters[0]}-{ordered_letters[-1]} INDEX GRID"
        else:
            title = "A-Z INDEX GRID"
        dedup_lines: list[str] = []
        seen_line_keys: set[str] = set()
        for line in lines:
            cleaned = line.strip()
            key = cleaned.lower()
            if not cleaned or key in seen_line_keys:
                continue
            seen_line_keys.add(key)
            dedup_lines.append(cleaned)
        bbox = (
            (min(xs0), min(ys0), max(xs1), max(ys1))
            if xs0 and ys0 and xs1 and ys1
            else None
        )
        merged.append(
            SiteSchematicPageSection(
                section_id=f"section:p{page_index}:alpha_index_merged",
                page_index=page_index,
                order_index=0,
                section_title=title,
                bbox=bbox,
                ordered_lines=tuple(dedup_lines),
                confidence=round(sum(confidences) / max(1, len(confidences)), 3) if confidences else 0.78,
                metadata={
                    "detector": "alpha_grid_merged",
                    "box_indicator": True,
                    "box_role": "alpha_index_grid",
                    "merged_count": len(alpha_sections),
                },
            )
        )
    merged = sorted(
        merged,
        key=lambda row: (
            9e9 if row.bbox is None else row.bbox[1],
            9e9 if row.bbox is None else row.bbox[0],
            row.section_title,
        ),
    )
    return [
        SiteSchematicPageSection(
            section_id=row.section_id,
            page_index=row.page_index,
            order_index=idx,
            section_title=row.section_title,
            bbox=row.bbox,
            ordered_lines=row.ordered_lines,
            confidence=row.confidence,
            metadata=row.metadata,
        )
        for idx, row in enumerate(merged, start=1)
    ]


def _dispatch_decomposed_page(
    *,
    page_index: int,
    text: str,
    classification: SheetClassification,
    overlay_tags: tuple[str, ...],
    coarse_regions: tuple[SiteSchematicRegion, ...],
    detail_regions: tuple[SiteSchematicDetailRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...],
    universal_tables: tuple = (),
    page_observation: SiteSchematicPageObservation | None = None,
    structure_graph: object | None = None,
    promoted_note_candidates: tuple[dict[str, object], ...] = (),
) -> ExtractedPageArtifacts:
    mixed_sheet_types = {"floorplan_detail", "equipment_room_layout", "installation_detail", "rack_detail"}
    if classification.sheet_type not in mixed_sheet_types or not pseudo_pages:
        artifacts = extract_by_sheet_type(
            page_index=page_index,
            text=text,
            sheet_type=classification.sheet_type,
            overlay_tags=overlay_tags,
            sheet_title=classification.sheet_title,
            regions=coarse_regions,
            universal_tables=universal_tables,
            promoted_note_candidates=promoted_note_candidates,
        )
        scoped_note_links = resolve_note_scope(
            page_index=page_index,
            note_clauses=artifacts.note_clauses,
            regions=coarse_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            page_observation=page_observation,
            structure_graph=structure_graph,
        )
        return replace(
            artifacts,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            scoped_note_links=scoped_note_links,
            note_clause_objects=_group_note_clauses_into_sections(
                note_clause_objects=_apply_note_scope(
                    note_clause_objects=artifacts.note_clause_objects,
                    scoped_note_links=scoped_note_links,
                ),
            ),
        )

    base_artifacts = extract_by_sheet_type(
        page_index=page_index,
        text=text,
        sheet_type=classification.sheet_type,
        overlay_tags=overlay_tags,
        sheet_title=classification.sheet_title,
        regions=coarse_regions,
        universal_tables=universal_tables,
        promoted_note_candidates=promoted_note_candidates,
    )
    routed: list[ExtractedPageArtifacts] = []
    for pseudo_page in pseudo_pages:
        routed.append(
            extract_by_sheet_type(
                page_index=page_index,
                text=text,
                sheet_type=classification.sheet_type,
                overlay_tags=overlay_tags,
                sheet_title=classification.sheet_title,
                regions=coarse_regions,
                pseudo_page=pseudo_page,
                universal_tables=universal_tables,
                promoted_note_candidates=promoted_note_candidates,
            )
        )
    merged = _merge_subregion_artifacts(page_index=page_index, rows=(base_artifacts, *tuple(routed)))
    scoped_note_links = resolve_note_scope(
        page_index=page_index,
        note_clauses=merged.note_clauses,
        regions=coarse_regions,
        subregions=subregions,
        pseudo_pages=pseudo_pages,
        page_observation=page_observation,
        structure_graph=structure_graph,
    )
    return replace(
        merged,
        regions=coarse_regions,
        detail_regions=detail_regions,
        subregions=subregions,
        pseudo_pages=pseudo_pages,
        scoped_note_links=scoped_note_links,
        note_clause_objects=_group_note_clauses_into_sections(
            note_clause_objects=_apply_note_scope(
                note_clause_objects=merged.note_clause_objects,
                scoped_note_links=scoped_note_links,
            ),
        ),
    )


def build_page_decomposition(
    *,
    page_index: int,
    text: str,
    classification: SheetClassification,
    page_observation: SiteSchematicPageObservation | None = None,
    universal_tables: tuple = (),
) -> tuple[tuple[SiteSchematicRegion, ...], tuple[SiteSchematicDetailRegion, ...], tuple[SiteSchematicSubregion, ...], tuple[SiteSchematicPseudoPage, ...]]:
    coarse_regions = build_page_regions(
        page_index=page_index,
        text=text,
        sheet_type=classification.sheet_type,
        sheet_number=classification.sheet_number,
        sheet_title=classification.sheet_title,
        page_observation=page_observation,
        universal_tables=tuple(universal_tables),
    )
    detail_regions = build_nested_detail_regions(
        page_index=page_index,
        text=text,
        regions=coarse_regions,
        sheet_type=classification.sheet_type,
        page_observation=page_observation,
    )
    subregions = classify_subregions(
        page_index=page_index,
        sheet_type=classification.sheet_type,
        detail_regions=detail_regions,
    )
    pseudo_pages = build_pseudo_pages(
        page_index=page_index,
        sheet_type=classification.sheet_type,
        text=text,
        regions=coarse_regions,
        subregions=subregions,
        page_observation=page_observation,
    )
    updated_regions: list[SiteSchematicRegion] = []
    for region in coarse_regions:
        children = [row for row in detail_regions if row.parent_region_id == region.region_id and row.bbox is not None]
        updated_region, _ = complete_region_bbox_from_children(region, children, table_anchors=tuple(universal_tables))
        updated_regions.append(updated_region)
    page_bbox = next((row.bbox for row in updated_regions if row.bbox is not None), (0.0, 0.0, 1.0, 1.0))
    updated_details = tuple(
        row if row.bbox is not None else replace(row, bbox=page_bbox, metadata={**dict(row.metadata), "bbox_completed_from_parent": True})
        for row in detail_regions
    )
    detail_by_id = {row.detail_region_id: row for row in updated_details}
    updated_subregions = tuple(
        row
        if row.bbox is not None
        else replace(
            row,
            bbox=(detail_by_id.get(row.detail_region_id).bbox if row.detail_region_id in detail_by_id else page_bbox),
            metadata={**dict(row.metadata), "bbox_completed_from_parent": True},
        )
        for row in subregions
    )
    subregion_by_id = {row.subregion_id: row for row in updated_subregions}
    updated_pseudos = tuple(
        row
        if row.bbox is not None
        else replace(
            row,
            bbox=(
                subregion_by_id.get(row.subregion_id).bbox
                if row.subregion_id and row.subregion_id in subregion_by_id
                else page_bbox
            ),
            metadata={**dict(row.metadata), "bbox_completed_from_parent": True},
        )
        for row in pseudo_pages
    )
    return (tuple(updated_regions), updated_details, updated_subregions, updated_pseudos)


def build_site_schematic_bundle_from_router_input(
    router_input: RouterInput,
    *,
    source_modality: str = "site_schematic_pdf",
) -> SiteSchematicBundle:
    metadata_map = dict(router_input.metadata) if isinstance(router_input.metadata, Mapping) else {}
    heuristic_only_detector = bool(metadata_map.get("symbol_detector_heuristic_only", False))
    section_detector_mode = "bundle_runtime_only_v1"
    page_texts = extract_page_texts(router_input)
    source_path = extract_path(router_input)
    raw_page_sections_by_page: dict[int, list] = {}
    if source_path and source_path.suffix.lower() == ".pdf":
        for i in range(1, len(page_texts) + 1):
            raw_page_sections_by_page[i] = detect_page_sections_from_pdf(pdf_path=source_path, page_index=i)
    model_registry = load_site_schematic_model_registry()
    initial_sheet_types = [classify_sheet(text).sheet_type for text in page_texts]
    preliminary_escalation = [
        choose_page_escalation_policy(
            sheet_family_hint=sheet_type,
            locality_confidence=0.5,
            table_family_confidence=0.5,
            column_ambiguity=0.4 if sheet_type in {"notes_spec", "legend_symbol", "schedule_sheet"} else 0.2,
            titleblock_confidence=0.6,
        )
        for sheet_type in initial_sheet_types
    ]
    page_observations, observation_diagnostics = build_site_schematic_page_observations(
        router_input=router_input,
        page_texts=page_texts,
        model_registry=model_registry,
        sheet_types=initial_sheet_types,
    )
    observation_diagnostics["holdout_escalation_hints"] = preliminary_escalation
    page_diag_map: dict[int, dict[str, object]] = {
        int(row.get("page_index", 0)): row
        for row in observation_diagnostics.get("pages", [])
        if isinstance(row, dict) and int(row.get("page_index", 0)) > 0
    }
    page_observation_by_index = {row.page_index: row for row in page_observations}
    page_modality_decisions: list[SiteSchematicPageModalityDecision] = []
    page_modality_map: dict[int, SiteSchematicPageModalityDecision] = {}
    for page_index, page_observation in page_observation_by_index.items():
        metadata = dict(page_observation.metadata or {})
        vector_path_count = int(metadata.get("vector_path_count", len(page_observation.vector_items)) or 0)
        image_count = int(metadata.get("image_count", 0) or 0)
        line_art_density = float(metadata.get("line_art_density", 0.0) or 0.0)
        table_count = len(page_observation.table_blocks)
        sheet_type = initial_sheet_types[page_index - 1] if page_index - 1 < len(initial_sheet_types) else "unknown"
        decision = classify_page_modality(
            page_index=page_index,
            sheet_type=sheet_type,
            page_text=page_observation.page_text,
            vector_path_count=vector_path_count,
            image_count=image_count,
            line_art_density=line_art_density,
            table_count=table_count,
        )
        calibrated = calibrate_modality_decision(
            modality=decision.modality,
            confidence=decision.confidence,
            vector_path_count=vector_path_count,
            image_count=image_count,
            line_art_density=line_art_density,
            text_density=float(decision.diagnostics.get("text_density", 0.0)),
        )
        calibrated_reasons = tuple([*decision.reasons, *calibrated.reasons])
        calibrated_diagnostics = {
            **dict(decision.diagnostics),
            **dict(calibrated.diagnostics),
            "ambiguous": 1.0 if calibrated.ambiguous else 0.0,
        }
        model_row = SiteSchematicPageModalityDecision(
            page_index=decision.page_index,
            sheet_type=decision.sheet_type,
            modality=calibrated.modality,
            confidence=calibrated.confidence,
            ambiguous=calibrated.ambiguous,
            scores=decision.scores,
            reasons=calibrated_reasons,
            diagnostics=calibrated_diagnostics,
        )
        page_modality_decisions.append(model_row)
        page_modality_map[page_index] = model_row
        page_diag = page_diag_map.get(page_index)
        if page_diag is not None:
            page_diag["page_modality"] = model_row.modality
            page_diag["page_modality_confidence"] = round(model_row.confidence, 4)
            page_diag["page_modality_ambiguous"] = bool(model_row.ambiguous)
            page_diag["page_modality_reasons"] = list(model_row.reasons)
            page_diag["page_modality_diagnostics"] = dict(model_row.diagnostics)
    model_detections_by_page, model_adapter_diag = load_model_primitive_detections(
        metadata=metadata_map,
        model_registry=model_registry,
        page_count=len(page_texts),
        packet_id=router_input.doc_id or router_input.filename or "unknown_packet",
    )
    overlay_hints = compute_document_overlay_hints(page_texts)
    page_rows: list[
        tuple[
            int,
            str,
            SheetClassification,
            tuple[str, ...],
            ExtractedPageArtifacts,
            tuple[SiteSchematicDetailRegion, ...],
            tuple[SiteSchematicSubregion, ...],
            tuple[SiteSchematicPseudoPage, ...],
            tuple[SiteSchematicScopedNoteLink, ...],
        ]
    ] = []
    all_regions: list[SiteSchematicRegion] = []
    all_detail_regions: list[SiteSchematicDetailRegion] = []
    all_subregions: list[SiteSchematicSubregion] = []
    all_pseudo_pages: list[SiteSchematicPseudoPage] = []
    all_scoped_note_links: list[SiteSchematicScopedNoteLink] = []
    all_universal_tables = []
    legend_entries: list[SiteSchematicLegendEntry] = []
    abbreviations: list[SiteSchematicAbbreviationEntry] = []
    outlet_type_definitions: list = []
    drawing_index_row_objects: list[SiteSchematicDrawingIndexRow] = []
    semantic_lineage_refs = []
    note_clause_objects: list = []
    mounting_rules: list = []
    termination_rules: list = []
    color_conventions: list = []
    environmental_requirements: list = []
    grounding_requirements: list = []
    testing_requirements: list = []
    labeling_requirements: list = []
    responsibility_assignments: list = []
    cable_rules: list = []
    pathway_rules: list = []
    service_loop_requirements: list = []
    all_vector_primitives: list[SiteSchematicVectorPrimitive] = []
    all_vector_primitive_validations: list[SiteSchematicVectorPrimitiveValidation] = []
    all_vector_primitive_graphs: list[SiteSchematicVectorPrimitiveGraph] = []
    all_measurement_candidates: list[SiteSchematicMeasurementCandidate] = []
    v0_v1_density_audit_rows: list[dict[str, object]] = []
    v0_v1_zero_guard_rows: list[dict[str, object]] = []
    v0_v1_leader_quality_rows: list[float] = []
    v0_v1_dimension_quality_rows: list[float] = []
    packet_note_pool: list[str] = []
    observation_counter: Counter[str] = Counter()
    overlay_counter: Counter[str] = Counter()
    sheet_counter: Counter[str] = Counter()

    structure_graph_diag_by_page: dict[int, dict[str, object]] = {}
    packet_id_for_tail_fix = (
        (router_input.doc_id or "").strip()
        or Path(router_input.filename or "unknown_packet.pdf").stem
    )
    packet_id_value = packet_id_for_tail_fix
    for page_index, text in enumerate(page_texts, start=1):
        page_observation = page_observation_by_index.get(page_index)
        page_text = (
            page_observation.page_text
            if (page_observation is not None and page_observation.page_text.strip() and page_observation.source_mode != "text_heuristic")
            else text
        )
        classification_input = text if text.strip() else page_text
        classification = classify_sheet(classification_input)
        if classification.sheet_type == "unknown":
            recovered_type = "schedule_sheet" if page_observation and page_observation.table_blocks else "floorplan_overall"
            classification = SheetClassification(
                sheet_number=classification.sheet_number,
                sheet_title=classification.sheet_title,
                sheet_type=recovered_type,
                confidence=max(classification.confidence, 0.42),
                evidence_codes=tuple((*classification.evidence_codes, "unknown_recovered")),
            )
        base_classification = classification
        promoted_note_candidates = tuple(
            promote_note_clauses_from_blocks(
                packet_id=packet_id_for_tail_fix,
                page_index=page_index,
                sheet_type=classification.sheet_type,
                layout_blocks=page_observation.layout_blocks if page_observation is not None else (),
                existing_note_count=0,
            )
        )
        overlay_tags = classify_overlay_tags(
            text,
            default_wireless=overlay_hints.get("default_wireless", False) and classification.sheet_type != "notes_spec",
            default_low_voltage=overlay_hints.get("default_low_voltage", False),
            sheet_type=classification.sheet_type,
        )
        page_vector_primitives: tuple[SiteSchematicVectorPrimitive, ...] = ()
        page_vector_graph: SiteSchematicVectorPrimitiveGraph | None = None
        page_density_audit: dict[str, object] = {}
        page_zero_guard: dict[str, object] = {}
        if page_observation is not None:
            v0_decision = page_modality_map.get(page_index)
            page_meta = dict(page_observation.metadata or {})
            vector_path_count = int(page_meta.get("vector_path_count", len(page_observation.vector_items)) or 0)
            image_count = int(page_meta.get("image_count", 0) or 0)
            line_art_density = float(page_meta.get("line_art_density", 0.0) or 0.0)
            extracted_primitives: list[VectorPrimitive] = []
            if page_observation.vector_items and v0_decision is not None and v0_decision.modality in {"vector_rich", "hybrid"}:
                extracted_primitives = extract_vector_primitives_from_vector_items(
                    list(page_observation.vector_items),
                    page_index=page_index,
                )
            deduped_primitives = dedup_vector_primitives(extracted_primitives)
            page_vector_primitives = tuple(
                SiteSchematicVectorPrimitive(
                    primitive_id=row.primitive_id,
                    primitive_kind=row.primitive_kind,
                    bbox=row.bbox,
                    page_index=row.page_index,
                    confidence=row.confidence,
                    source_mode=row.source_mode,
                    provider=row.provider,
                    metadata=row.metadata,
                )
                for row in deduped_primitives
            )
            primitive_validations = tuple(
                validate_vector_primitive(row)
                for row in deduped_primitives
            )
            all_vector_primitive_validations.extend(
                SiteSchematicVectorPrimitiveValidation(
                    primitive_id=row.primitive_id,
                    valid=row.valid,
                    quality_score=row.quality_score,
                    candidate_kind=row.candidate_kind,
                    reasons=row.reasons,
                )
                for row in primitive_validations
            )
            validated_primitive_count = sum(1 for row in primitive_validations if row.valid)
            density_audit = audit_primitive_density(
                raw_count=len(extracted_primitives),
                deduped_count=len(deduped_primitives),
                validated_count=validated_primitive_count,
            )
            page_density_audit = {
                "raw_count": density_audit.raw_count,
                "deduped_count": density_audit.deduped_count,
                "validated_count": density_audit.validated_count,
                "dedup_effectiveness": round(density_audit.dedup_effectiveness, 4),
                "sparse_graph": density_audit.sparse_graph,
                "overly_dense_graph": density_audit.overly_dense_graph,
                "sanity_ok": density_audit.sanity_ok,
            }
            v0_v1_density_audit_rows.append({"page_index": page_index, **page_density_audit})
            zero_guard = detect_suspicious_zero_primitive_page(
                modality=v0_decision.modality if v0_decision is not None else "unknown",
                vector_path_count=vector_path_count,
                image_count=image_count,
                line_art_density=line_art_density,
                primitive_count=len(deduped_primitives),
                validated_primitive_count=validated_primitive_count,
            )
            page_zero_guard = {
                "suspicious": zero_guard.suspicious,
                "severity": zero_guard.severity,
                "reasons": list(zero_guard.reasons),
            }
            v0_v1_zero_guard_rows.append({"page_index": page_index, **page_zero_guard})
            if deduped_primitives:
                graph_primitives = tuple(row for idx, row in enumerate(deduped_primitives) if primitive_validations[idx].valid) or tuple(deduped_primitives)
                primitive_graph = build_vector_primitive_graph(
                    graph_primitives,
                    page_index=page_index,
                )
                by_id = {row.primitive_id: row for row in graph_primitives}
                for primitive_id in primitive_graph.leader_candidate_ids:
                    quality = score_leader_semantic_quality(
                        by_id[primitive_id],
                        nearby_text_hint=bool(page_observation.page_text.strip()),
                    )
                    v0_v1_leader_quality_rows.append(1.0 if quality.valid else 0.0)
                for primitive_id in primitive_graph.dimension_candidate_ids:
                    quality = score_dimension_semantic_quality(
                        by_id[primitive_id],
                        nearby_numeric_text=bool(re.search(r"\d", page_observation.page_text or "")),
                        witness_line_hint=True,
                    )
                    v0_v1_dimension_quality_rows.append(1.0 if quality.valid else 0.0)
                page_vector_graph = SiteSchematicVectorPrimitiveGraph(
                    page_index=primitive_graph.page_index,
                    primitive_ids=primitive_graph.primitive_ids,
                    leader_candidate_ids=primitive_graph.leader_candidate_ids,
                    connector_candidate_ids=primitive_graph.connector_candidate_ids,
                    dimension_candidate_ids=primitive_graph.dimension_candidate_ids,
                    diagnostics={
                        **dict(primitive_graph.diagnostics),
                        "raw_primitive_count": float(len(extracted_primitives)),
                        "deduped_primitive_count": float(len(deduped_primitives)),
                        "validated_primitive_count": float(validated_primitive_count),
                        "dedup_effectiveness": float(density_audit.dedup_effectiveness),
                        "density_sanity_ok": 1.0 if density_audit.sanity_ok else 0.0,
                        "suspicious_zero_primitive": 1.0 if zero_guard.suspicious else 0.0,
                    },
                )
                all_vector_primitives.extend(page_vector_primitives)
                all_vector_primitive_graphs.append(page_vector_graph)
                all_measurement_candidates.extend(
                    SiteSchematicMeasurementCandidate(
                        measurement_id=row.measurement_id,
                        page_index=row.page_index,
                        bbox=row.bbox,
                        measurement_source=row.measurement_source,
                        scale_source=row.scale_source,
                        confidence=row.confidence,
                        metadata=row.metadata,
                    )
                    for row in build_measurement_candidates_from_vector_graph(primitive_graph)
                )
        coarse_regions, detail_regions, subregions, pseudo_pages = build_page_decomposition(
            page_index=page_index,
            text=page_text,
            classification=classification,
            page_observation=page_observation,
        )
        provisional_universal_tables = build_universal_tables_for_page(
            packet_id=router_input.doc_id or router_input.filename or "unknown_packet",
            pdf_id=Path(router_input.filename or router_input.doc_id or "unknown_pdf").name,
            page_index=page_index,
            sheet_type=classification.sheet_type,
            sheet_number=classification.sheet_number,
            sheet_title=classification.sheet_title,
            regions=coarse_regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            page_observation=page_observation,
            structure_graph=None,
        )
        coarse_regions, detail_regions, subregions, pseudo_pages = build_page_decomposition(
            page_index=page_index,
            text=page_text,
            classification=classification,
            page_observation=page_observation,
            universal_tables=provisional_universal_tables,
        )
        page_width = _infer_page_width(page_observation)
        provisional_structure_graph = build_page_structure_graph(
            page_index=page_index,
            sheet_type=classification.sheet_type,
            layout_blocks=page_observation.layout_blocks if page_observation is not None else (),
            universal_tables=provisional_universal_tables,
            regions=coarse_regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            vector_primitives=page_vector_primitives,
            page_width=page_width,
        )
        if False and classification.sheet_type != base_classification.sheet_type:
            coarse_regions, detail_regions, subregions, pseudo_pages = build_page_decomposition(
                page_index=page_index,
                text=page_text,
                classification=classification,
                page_observation=page_observation,
            )
            provisional_universal_tables = build_universal_tables_for_page(
                packet_id=router_input.doc_id or router_input.filename or "unknown_packet",
                pdf_id=Path(router_input.filename or router_input.doc_id or "unknown_pdf").name,
                page_index=page_index,
                sheet_type=classification.sheet_type,
                sheet_number=classification.sheet_number,
                sheet_title=classification.sheet_title,
                regions=coarse_regions,
                detail_regions=detail_regions,
                subregions=subregions,
                pseudo_pages=pseudo_pages,
                page_observation=page_observation,
                structure_graph=None,
            )
            coarse_regions, detail_regions, subregions, pseudo_pages = build_page_decomposition(
                page_index=page_index,
                text=page_text,
                classification=classification,
                page_observation=page_observation,
                universal_tables=provisional_universal_tables,
            )
        page_universal_tables = build_universal_tables_for_page(
            packet_id=router_input.doc_id or router_input.filename or "unknown_packet",
            pdf_id=Path(router_input.filename or router_input.doc_id or "unknown_pdf").name,
            page_index=page_index,
            sheet_type=classification.sheet_type,
            sheet_number=classification.sheet_number,
            sheet_title=classification.sheet_title,
            regions=coarse_regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            page_observation=page_observation,
            structure_graph=None,
        )
        final_structure_graph = build_page_structure_graph(
            page_index=page_index,
            sheet_type=classification.sheet_type,
            layout_blocks=page_observation.layout_blocks if page_observation is not None else (),
            universal_tables=page_universal_tables,
            regions=coarse_regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            vector_primitives=page_vector_primitives,
            page_width=page_width,
        )
        structure_graph_diag_by_page[page_index] = {
            **final_structure_graph.diagnostics,
            "classification_refined": classification.sheet_type != base_classification.sheet_type,
            "base_sheet_type": base_classification.sheet_type,
            "final_sheet_type": classification.sheet_type,
            "page_modality": page_modality_map.get(page_index).modality if page_index in page_modality_map else "unknown",
            "vector_primitive_count": len(page_vector_primitives),
            "vector_graph_present": page_vector_graph is not None,
            "primitive_density_audit": page_density_audit,
            "suspicious_zero_primitive_guard": page_zero_guard,
        }
        artifacts = _dispatch_decomposed_page(
            page_index=page_index,
            text=text,
            classification=classification,
            overlay_tags=overlay_tags,
            coarse_regions=coarse_regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            universal_tables=page_universal_tables,
            page_observation=page_observation,
            structure_graph=None,
            promoted_note_candidates=promoted_note_candidates,
        )
        artifacts = _ensure_page_level_note_clause_presence(
            packet_id=packet_id_for_tail_fix,
            page_index=page_index,
            sheet_type=classification.sheet_type,
            page_text=(page_observation.page_text if page_observation is not None else page_text),
            artifacts=artifacts,
        )
        (
            lined_legend_entries,
            lined_abbreviations,
            lined_outlet_type_definitions,
            lined_drawing_index_rows,
            page_lineage_refs,
        ) = attach_semantic_lineage(
            universal_tables=page_universal_tables,
            legend_entries=artifacts.legend_entries,
            abbreviations=artifacts.abbreviations,
            outlet_type_definitions=artifacts.outlet_type_definitions,
            drawing_index_rows=artifacts.drawing_index_row_objects,
        )
        artifacts = replace(
            artifacts,
            legend_entries=lined_legend_entries,
            abbreviations=lined_abbreviations,
            outlet_type_definitions=lined_outlet_type_definitions,
            drawing_index_row_objects=lined_drawing_index_rows,
        )
        page_diag = page_diag_map.get(page_index)
        if page_diag is not None:
            detail_conf = [row.confidence for row in detail_regions]
            pseudo_clustering_applied = any(bool(row.metadata.get("clustering_applied")) for row in pseudo_pages)
            page_diag["sheet_type"] = classification.sheet_type
            page_diag["sheet_number"] = classification.sheet_number
            page_diag["sheet_title"] = classification.sheet_title
            page_diag["decomposition_confidence"] = round(sum(detail_conf) / len(detail_conf), 4) if detail_conf else 0.0
            page_diag["pseudo_page_count"] = len(pseudo_pages)
            page_diag["scoped_note_count"] = len(artifacts.scoped_note_links)
            page_diag["clustering_applied"] = pseudo_clustering_applied
            page_diag["structure_graph"] = structure_graph_diag_by_page.get(page_index, {})
            page_diag["promoted_note_candidate_count"] = len(promoted_note_candidates)
            page_diag["vector_primitive_count"] = len(page_vector_primitives)
            page_diag["vector_graph_candidate_counts"] = (
                dict(page_vector_graph.diagnostics) if page_vector_graph is not None else {}
            )
            page_diag["primitive_density_audit"] = dict(page_density_audit)
            page_diag["suspicious_zero_primitive_guard"] = dict(page_zero_guard)
        page_rows.append((page_index, text, classification, overlay_tags, artifacts, detail_regions, subregions, pseudo_pages, artifacts.scoped_note_links))
        all_regions.extend(coarse_regions)
        all_detail_regions.extend(detail_regions)
        all_subregions.extend(subregions)
        all_pseudo_pages.extend(pseudo_pages)
        all_scoped_note_links.extend(artifacts.scoped_note_links)
        all_universal_tables.extend(page_universal_tables)
        legend_entries.extend(artifacts.legend_entries)
        abbreviations.extend(artifacts.abbreviations)
        outlet_type_definitions.extend(artifacts.outlet_type_definitions)
        drawing_index_row_objects.extend(artifacts.drawing_index_row_objects)
        semantic_lineage_refs.extend(page_lineage_refs)
        note_clause_objects.extend(artifacts.note_clause_objects)
        mounting_rules.extend(artifacts.mounting_rules)
        termination_rules.extend(artifacts.termination_rules)
        color_conventions.extend(artifacts.color_conventions)
        environmental_requirements.extend(artifacts.environmental_requirements)
        grounding_requirements.extend(artifacts.grounding_requirements)
        testing_requirements.extend(artifacts.testing_requirements)
        labeling_requirements.extend(artifacts.labeling_requirements)
        responsibility_assignments.extend(artifacts.responsibility_assignments)
        cable_rules.extend(artifacts.cable_rules)
        pathway_rules.extend(artifacts.pathway_rules)
        service_loop_requirements.extend(artifacts.service_loop_requirements)
        packet_note_pool.extend(artifacts.note_clauses)
        for tag in overlay_tags:
            overlay_counter[tag] += 1
        sheet_counter[classification.sheet_type] += 1

    deduped_packet_notes = _dedupe_text(packet_note_pool)
    pages: list[SiteSchematicPage] = []
    page_sections: list[SiteSchematicPageSection] = []
    observations: list[SiteSchematicObservation] = []
    all_symbol_instances: list[SiteSchematicSymbolInstance] = []
    all_symbol_links: list[SiteSchematicSymbolLink] = []
    all_symbol_resolution_outcomes: list[SiteSchematicSymbolResolutionOutcome] = []
    all_symbol_candidate_inputs: list[SiteSchematicSymbolCandidateInput] = []
    all_symbol_candidate_groups: list[SiteSchematicSymbolCandidateGroup] = []
    all_legend_grounding_entries: list[SiteSchematicLegendGroundingEntry] = []
    all_grounded_symbols: list[SiteSchematicGroundedSymbol] = []
    packet_v2_memory_entries: dict[tuple[str, str], LegendGroundingEntry] = {}
    all_v2_page_rows: list[dict[str, object]] = []
    all_device_instances: list[SiteSchematicDeviceInstance] = []
    all_outlet_instances: list[SiteSchematicOutletInstance] = []
    all_rooms: list[SiteSchematicRoom] = []
    all_closets: list[SiteSchematicCloset] = []
    all_racks: list[SiteSchematicRack] = []
    all_riser_edges: list[SiteSchematicRiserEdge] = []
    all_topology_segments: list[SiteSchematicTopologySegment] = []
    all_topology_endpoints: list[SiteSchematicTopologyEndpoint] = []
    all_topology_relations: list[SiteSchematicTopologyRelation] = []
    topology_profile_endpoint_counts: Counter[str] = Counter()
    topology_profile_relation_counts: Counter[str] = Counter()
    topology_profile_abstain_counts: Counter[str] = Counter()
    grounding_strengthened_by_profile: Counter[str] = Counter()
    grounding_strengthened_by_family: Counter[str] = Counter()
    grounding_strengthened_samples: list[dict[str, object]] = []
    grounding_rejected_samples: list[dict[str, object]] = []
    topology_endpoint_bridge_promotions: Counter[str] = Counter()
    topology_promoted_endpoint_samples: list[dict[str, object]] = []
    vector_primitives_by_page: dict[int, list[SiteSchematicVectorPrimitive]] = {}
    for row in all_vector_primitives:
        vector_primitives_by_page.setdefault(row.page_index, []).append(row)

    for page_index, text, classification, overlay_tags, artifacts, detail_regions, subregions, pseudo_pages, scoped_note_links in page_rows:
        symbol_instances: tuple[SiteSchematicSymbolInstance, ...] = ()
        symbol_links: tuple[SiteSchematicSymbolLink, ...] = ()
        symbol_resolution_outcomes: tuple[SiteSchematicSymbolResolutionOutcome, ...] = ()
        if classification.sheet_type in {"floorplan_overall", "floorplan_detail", "riser_diagram", "equipment_room_layout", "installation_detail", "rack_detail"}:
            model_detections = model_detections_by_page.get(page_index, ())
            if model_detections:
                model_instances = materialize_symbol_instances_from_detections(
                    detections=model_detections,
                    overlay_tags=overlay_tags,
                    page_index=page_index,
                    default_region_id=next((row.region_id for row in artifacts.regions if row.kind in {"plan_body_block", "detail_block"}), ""),
                )
                heuristic_hints = detect_primitive_symbols(
                    page_index=page_index,
                    text=text,
                    overlay_tags=overlay_tags,
                    regions=artifacts.regions,
                    legend_entries=tuple(legend_entries),
                    abbreviations=tuple(abbreviations),
                    room_labels=artifacts.room_labels,
                )
                legend_tokens = {entry.symbol_token.upper() for entry in legend_entries if entry.symbol_token}
                low_voltage_hint_tokens = {"WN", "ZN"}
                if "low_voltage" in set(overlay_tags):
                    heuristic_hints = tuple(
                        row
                        for row in heuristic_hints
                        if row.token.upper() in legend_tokens or row.token.upper() in low_voltage_hint_tokens
                    )
                else:
                    heuristic_hints = tuple(row for row in heuristic_hints if row.token.upper() in legend_tokens)
                symbol_instances = _merge_symbol_instances(
                    model_rows=model_instances,
                    heuristic_rows=heuristic_hints,
                )
            else:
                symbol_instances = detect_primitive_symbols(
                    page_index=page_index,
                    text=text,
                    overlay_tags=overlay_tags,
                    regions=artifacts.regions,
                    legend_entries=tuple(legend_entries),
                    abbreviations=tuple(abbreviations),
                    room_labels=artifacts.room_labels,
                )
                if not heuristic_only_detector:
                    primitive_detections = map_symbol_instances_to_primitive_detections(
                        symbol_instances=symbol_instances,
                        packet_id=router_input.doc_id or router_input.filename or "unknown_packet",
                    )
                    if primitive_detections:
                        default_region_id = symbol_instances[0].region_id if symbol_instances else ""
                        symbol_instances = materialize_symbol_instances_from_detections(
                            detections=primitive_detections,
                            overlay_tags=overlay_tags,
                            page_index=page_index,
                            default_region_id=default_region_id,
                        )
            symbol_instances = _apply_region_profile_metadata(
                symbol_instances=symbol_instances,
                sheet_type=classification.sheet_type,
                regions=artifacts.regions,
                detail_regions=detail_regions,
                subregions=subregions,
                pseudo_pages=pseudo_pages,
            )
            symbol_links = link_symbol_instances(
                symbol_instances=symbol_instances,
                legend_entries=tuple(legend_entries),
                note_clauses=_dedupe_text([*deduped_packet_notes, *artifacts.note_clauses]),
                room_labels=artifacts.room_labels,
            )
            all_symbol_instances.extend(symbol_instances)
        symbol_candidate_inputs = _build_symbol_candidate_inputs_for_page(
            artifact_id=router_input.doc_id or router_input.filename,
            page_index=page_index,
            sheet_type=classification.sheet_type,
            sheet_number=classification.sheet_number,
            sheet_title=classification.sheet_title,
            page_observation=page_observation_by_index.get(page_index),
            regions=artifacts.regions,
            detail_regions=detail_regions,
            subregions=subregions,
            pseudo_pages=pseudo_pages,
            scoped_note_links=scoped_note_links,
            legend_entries=artifacts.legend_entries,
            abbreviations=artifacts.abbreviations,
            room_labels=artifacts.room_labels,
        )
        all_symbol_candidate_inputs.extend(symbol_candidate_inputs)
        v2_seed_primitives: list[object] = list(vector_primitives_by_page.get(page_index, []))
        if not v2_seed_primitives:
            v2_seed_primitives = [
                {
                    "primitive_id": row.candidate_id,
                    "primitive_kind": "polyline",
                    "bbox": row.bbox,
                }
                for row in symbol_candidate_inputs
                if row.bbox is not None
            ]
        v2_text_hints = [tok for tok in _clean(text).split(" ")[:180] if tok]
        v2_alias_hints = list(
            {
                tok.strip("()[]{}.,:;")
                for tok in text.split()
                if re.match(r"^[A-Z][A-Z0-9/-]{0,10}$", tok.strip("()[]{}.,:;"))
            }
        )
        lowered_text = text.lower()
        v2_semantic_hints: list[str] = []
        if "intercom" in lowered_text:
            v2_semantic_hints.append("INTERCOM")
        if "wireless access point" in lowered_text or " wap " in f" {lowered_text} ":
            v2_semantic_hints.append("WAP")
        if "door contact" in lowered_text:
            v2_semantic_hints.append("DC")
        if "zigbee" in lowered_text:
            v2_semantic_hints.append("ZN")
        if "telephone" in lowered_text or "wall phone" in lowered_text or "voice outlet" in lowered_text:
            v2_semantic_hints.append("PHONE")
        if "junction box" in lowered_text:
            v2_semantic_hints.append("JB")
        if "tmgb" in lowered_text or "tgb" in lowered_text or "grounding busbar" in lowered_text:
            v2_semantic_hints.append("TGB")
        if "speaker" in lowered_text or " pa " in f" {lowered_text} ":
            v2_semantic_hints.append("PA")
        v2_page_candidates = group_symbol_candidates_from_primitives(
            page_index=page_index,
            vector_primitives=v2_seed_primitives,
            nearby_text_hints=[*v2_text_hints, *v2_alias_hints, *v2_semantic_hints],
        )
        v2_legend_dictionary_local = build_legend_grounding_dictionary(
            page_index=page_index,
            legend_entries=[entry for entry in artifacts.legend_entries if entry.page_index == page_index],
        )
        v2_legend_dictionary = [
            *v2_legend_dictionary_local,
            *packet_v2_memory_entries.values(),
        ]
        v2_grounded_rows = resolve_grounded_symbols(
            candidates=v2_page_candidates,
            legend_dictionary=v2_legend_dictionary,
            sheet_type=classification.sheet_type,
            packet_id=packet_id_value,
        )
        for row in v2_grounded_rows:
            if row.status != "grounded" or not row.family or row.family == "unknown_symbol_group":
                continue
            alias_tokens = tuple(
                str(tok).upper()
                for tok in row.metadata.get("alias_tokens", ())
                if str(tok).strip()
            ) or tuple(
                str(tok).upper()
                for tok in row.supporting_text_hints
                if re.match(r"^[A-Z][A-Z0-9/-]{0,10}$", str(tok).strip())
            )
            memory_label = row.semantic_meaning or row.family.replace("_", " ")
            memory_entry = LegendGroundingEntry(
                legend_id=f"memory:{packet_id_value}:{page_index}:{row.candidate_id}",
                page_index=page_index,
                family=row.family,
                raw_label=memory_label,
                aliases=alias_tokens or (memory_label,),
                source_row_id=f"memory:{row.candidate_id}",
                source_cell_ids=(),
                bbox=row.bbox,
                confidence=min(0.98, max(0.6, float(row.confidence))),
            )
            for alias in memory_entry.aliases:
                packet_v2_memory_entries[(str(alias).upper(), memory_entry.family)] = memory_entry
        all_symbol_candidate_groups.extend(
            SiteSchematicSymbolCandidateGroup(
                candidate_id=row.candidate_id,
                page_index=row.page_index,
                bbox=row.bbox,
                primitive_ids=tuple(row.primitive_ids),
                text_hints=tuple(row.text_hints),
                family_candidates=tuple(row.family_candidates),
                confidence=row.confidence,
                metadata=row.metadata,
            )
            for row in v2_page_candidates
        )
        all_legend_grounding_entries.extend(
            SiteSchematicLegendGroundingEntry(
                legend_id=row.legend_id,
                page_index=row.page_index,
                family=row.family,
                raw_label=row.raw_label,
                aliases=tuple(row.aliases),
                source_row_id=row.source_row_id,
                source_cell_ids=tuple(row.source_cell_ids),
                bbox=row.bbox,
                confidence=row.confidence,
            )
            for row in v2_legend_dictionary_local
        )
        all_grounded_symbols.extend(
            SiteSchematicGroundedSymbol(
                grounded_id=row.grounded_id,
                page_index=row.page_index,
                candidate_id=row.candidate_id,
                family=row.family,
                semantic_meaning=row.semantic_meaning,
                bbox=row.bbox,
                legend_ids=tuple(row.legend_ids),
                supporting_text_hints=tuple(row.supporting_text_hints),
                confidence=row.confidence,
                status=row.status,
                metadata=row.metadata,
            )
            for row in v2_grounded_rows
        )
        grounded_on_page = [row for row in v2_grounded_rows if row.status == "grounded"]
        connector_required = classification.sheet_type in {
            "riser_diagram",
            "equipment_room_layout",
            "rack_detail",
            "installation_detail",
            "floorplan_overall",
            "floorplan_detail",
        }
        connector_ok = any(bool(row.metadata.get("connector_grounding_ok", False)) for row in grounded_on_page)
        all_v2_page_rows.append(
            {
                "page_index": page_index,
                "sheet_type": classification.sheet_type,
                "legend_grounding_ok": len(v2_legend_dictionary) > 0,
                "connector_required": connector_required,
                "connector_grounding_ok": connector_ok if connector_required else True,
            }
        )
        devices, outlets = _build_device_and_outlet_instances(page_index=page_index, symbol_instances=symbol_instances)
        all_device_instances.extend(devices)
        all_outlet_instances.extend(outlets)
        all_rooms.extend(_build_room_objects(page_index=page_index, labels=artifacts.room_labels))
        all_closets.extend(_build_closets(page_index=page_index, labels=artifacts.room_labels))
        all_racks.extend(_build_racks(page_index=page_index, text=text))
        all_riser_edges.extend(_build_riser_edges(page_index=page_index, text=text))
        all_topology_segments.extend(_build_topology_segments(page_index=page_index, text=text))
        topology_endpoints, topology_relations, topology_segments, topology_riser_edges, topology_diag = build_topology_for_page(
            page_index=page_index,
            sheet_type=classification.sheet_type,
            symbol_instances=symbol_instances,
            symbol_links=symbol_links,
            note_clauses=_dedupe_text([*deduped_packet_notes, *artifacts.note_clauses]),
            vector_graph_diagnostics=dict(page_vector_graph.diagnostics) if page_vector_graph is not None else None,
        )
        strengthened_links, grounding_diag = strengthen_symbol_links_with_topology(
            symbol_instances=symbol_instances,
            symbol_links=symbol_links,
            topology_endpoints=topology_endpoints,
            topology_relations=topology_relations,
        )
        if strengthened_links != symbol_links:
            symbol_links = strengthened_links
            topology_endpoints, topology_relations, topology_segments, topology_riser_edges, topology_diag = build_topology_for_page(
                page_index=page_index,
                sheet_type=classification.sheet_type,
                symbol_instances=symbol_instances,
                symbol_links=symbol_links,
                note_clauses=_dedupe_text([*deduped_packet_notes, *artifacts.note_clauses]),
                vector_graph_diagnostics=dict(page_vector_graph.diagnostics) if page_vector_graph is not None else None,
            )
        all_topology_endpoints.extend(topology_endpoints)
        all_topology_relations.extend(topology_relations)
        all_topology_segments.extend(topology_segments)
        all_riser_edges.extend(topology_riser_edges)
        topology_profile_endpoint_counts.update(dict(topology_diag.get("profile_endpoint_counts", {})))
        topology_profile_relation_counts.update(dict(topology_diag.get("profile_relation_counts", {})))
        topology_profile_abstain_counts.update(dict(topology_diag.get("profile_abstain_counts", {})))
        symbol_resolution_outcomes = build_symbol_resolution_outcomes(
            symbol_instances=symbol_instances,
            symbol_links=symbol_links,
            legend_entries=tuple(artifacts.legend_entries),
        )
        all_symbol_links.extend(symbol_links)
        all_symbol_resolution_outcomes.extend(symbol_resolution_outcomes)

        grounding_strengthened_by_profile.update(dict(grounding_diag.get("strengthened_by_profile", {})))
        grounding_strengthened_by_family.update(dict(grounding_diag.get("strengthened_by_family", {})))
        for row in grounding_diag.get("strengthened_samples", []):
            if len(grounding_strengthened_samples) < 64:
                grounding_strengthened_samples.append(dict(row))
        for row in grounding_diag.get("rejected_samples", []):
            if len(grounding_rejected_samples) < 64:
                grounding_rejected_samples.append(dict(row))
        topology_endpoint_bridge_promotions.update(dict(topology_diag.get("endpoint_bridge_promotions", {})))
        for row in topology_diag.get("promoted_endpoint_samples", []):
            if len(topology_promoted_endpoint_samples) < 32:
                topology_promoted_endpoint_samples.append(dict(row))

        detected_page_sections: list[SiteSchematicPageSection] = [
            SiteSchematicPageSection(
                section_id=row.section_id,
                page_index=row.page_index,
                order_index=row.order_index,
                section_title=row.title,
                bbox=row.bbox,
                ordered_lines=row.content_lines,
                confidence=row.confidence,
                metadata=dict(row.metadata or {}),
            )
            for row in raw_page_sections_by_page.get(page_index, [])
        ]
        fallback_sections = (
            _derive_page_sections_from_note_groups(
                page_index=page_index,
                note_clause_objects=artifacts.note_clause_objects,
            )
            if classification.sheet_type == "notes_spec"
            else ()
        )
        drawing_index_section = _drawing_index_page_section_from_rows(
            page_index=page_index,
            drawing_rows=artifacts.drawing_index_row_objects,
        )
        detected_page_sections = _merge_page_sections(
            page_index=page_index,
            primary=detected_page_sections,
            extras=fallback_sections,
            drawing_index_section=drawing_index_section,
        )

        page = SiteSchematicPage(
            page_index=page_index,
            page_label=f"page_{page_index}",
            sheet_type=classification.sheet_type,
            overlay_tags=overlay_tags,
            zones=_zone_names_from_regions(artifacts.regions),
            legend_entries=_dedupe_text([entry.description for entry in artifacts.legend_entries]),
            note_clauses=artifacts.note_clauses,
            room_labels=artifacts.room_labels,
            equipment_labels=artifacts.equipment_labels,
            sheet_number=classification.sheet_number,
            sheet_title=classification.sheet_title,
            region_ids=tuple(region.region_id for region in all_regions if region.page_index == page_index),
            detail_region_ids=tuple(region.detail_region_id for region in detail_regions),
            subregion_ids=tuple(region.subregion_id for region in subregions),
            pseudo_page_ids=tuple(row.pseudo_page_id for row in pseudo_pages),
            symbol_instance_ids=tuple(item.instance_id for item in symbol_instances),
            symbol_link_ids=tuple(item.link_id for item in symbol_links),
            drawing_index_rows=artifacts.drawing_index_rows,
            review_required=classification.sheet_type == "unknown" or (len(symbol_links) >= 8 and (sum(1 for link in symbol_links if link.status == "unresolved") / max(len(symbol_links), 1)) > 0.85),
            metadata={
                "sheet_confidence": classification.confidence,
                "sheet_evidence_codes": list(classification.evidence_codes),
                "scoped_notes": len(scoped_note_links),
                "symbol_candidate_inputs": len(symbol_candidate_inputs),
                "observation_provider": page_observation_by_index.get(page_index).provider if page_index in page_observation_by_index else "text_heuristic",
                "topology_endpoints": len(topology_endpoints),
                "topology_relations": len(topology_relations),
                "topology_abstain_count": sum(1 for row in topology_relations if row.status != "inferred"),
                "universal_table_count": len(page_universal_tables),
                "detected_page_section_count": len(detected_page_sections),
                "section_detector_mode": section_detector_mode,
            },
        )
        pages.append(page)
        page_sections.extend(detected_page_sections)
        observations.extend(
            _emit_observations(
                page_index=page_index,
                sheet_type=classification.sheet_type,
                overlay_tags=overlay_tags,
                regions=artifacts.regions,
                legend_entries=artifacts.legend_entries,
                abbreviations=artifacts.abbreviations,
                outlet_type_definitions=artifacts.outlet_type_definitions,
                note_clauses=artifacts.note_clauses,
                room_labels=artifacts.room_labels,
                equipment_labels=artifacts.equipment_labels,
                drawing_index_rows=artifacts.drawing_index_rows,
                symbol_instances=symbol_instances,
                symbol_links=symbol_links,
                counter=observation_counter,
            )
        )

    graph = build_packet_graph(
        pages=tuple(pages),
        regions=tuple(all_regions),
        legend_entries=tuple(legend_entries),
        abbreviations=tuple(abbreviations),
        drawing_index_rows=tuple(drawing_index_row_objects),
        note_clauses=tuple(note_clause_objects),
        mounting_rules=tuple(mounting_rules),
        termination_rules=tuple(termination_rules),
        environmental_requirements=tuple(environmental_requirements),
        grounding_requirements=tuple(grounding_requirements),
        testing_requirements=tuple(testing_requirements),
        labeling_requirements=tuple(labeling_requirements),
        responsibility_assignments=tuple(responsibility_assignments),
        cable_rules=tuple(cable_rules),
        pathway_rules=tuple(pathway_rules),
        service_loop_requirements=tuple(service_loop_requirements),
        device_instances=tuple(all_device_instances),
        outlet_instances=tuple(all_outlet_instances),
        rooms=tuple(all_rooms),
        closets=tuple(all_closets),
        racks=tuple(all_racks),
        riser_edges=tuple(all_riser_edges),
        topology_endpoints=tuple(all_topology_endpoints),
        topology_relations=tuple(all_topology_relations),
        symbol_instances=tuple(all_symbol_instances),
        symbol_links=tuple(all_symbol_links),
        symbol_resolution_outcomes=tuple(all_symbol_resolution_outcomes),
        detail_regions=tuple(all_detail_regions),
        subregions=tuple(all_subregions),
        pseudo_pages=tuple(all_pseudo_pages),
        scoped_note_links=tuple(all_scoped_note_links),
    )
    (
        reasoning_findings,
        consistency_checks,
        contradiction_flags,
        anchor_reconciliation_suggestions,
        topology_review_suggestions,
        reasoning_diagnostics,
    ) = build_bounded_graph_reasoning(
        graph=graph,
        symbol_instances=tuple(all_symbol_instances),
        symbol_links=tuple(all_symbol_links),
        topology_endpoints=tuple(all_topology_endpoints),
        topology_relations=tuple(all_topology_relations),
    )
    (
        packet_reasoning_summary,
        family_consistency_summaries,
        review_queue_summary,
        topology_coverage_summary,
        profile_qa_summaries,
    ) = build_reasoning_summaries(
        findings=reasoning_findings,
        symbol_links=tuple(all_symbol_links),
        topology_endpoints=tuple(all_topology_endpoints),
        topology_relations=tuple(all_topology_relations),
    )
    typed_pages = sum(1 for page in pages if page.sheet_type != "unknown")
    packet_v0_v1_summary_raw = summarize_packet_v0_v1(
        packet_id=(router_input.doc_id or Path(router_input.filename or "unknown_packet.pdf").stem),
        page_modality_rows=[row.to_dict() for row in page_modality_decisions],
        primitive_graph_rows=[
            {
                "primitive_count": int(row.diagnostics.get("primitive_count", 0.0)),
                "validated_primitive_count": int(row.diagnostics.get("validated_primitive_count", row.diagnostics.get("primitive_count", 0.0))),
                "leader_candidate_count": len(row.leader_candidate_ids),
                "dimension_candidate_count": len(row.dimension_candidate_ids),
                "suspicious_zero_primitive": bool(row.diagnostics.get("suspicious_zero_primitive", 0.0)),
            }
            for row in all_vector_primitive_graphs
        ],
    )
    suspicious_zero_primitive_page_failures = sum(
        1 for row in v0_v1_zero_guard_rows if bool(row.get("suspicious", False))
    )
    suspicious_zero_primitive_packet_failures = 1 if suspicious_zero_primitive_page_failures > 0 else 0
    density_rows_with_raw = [row for row in v0_v1_density_audit_rows if int(row.get("raw_count", 0) or 0) > 0]
    primitive_dedup_effectiveness_rate = round(
        (
            sum(float(row.get("dedup_effectiveness", 0.0) or 0.0) for row in density_rows_with_raw)
            / max(1, len(density_rows_with_raw))
        ),
        4,
    )
    primitive_density_sanity_rate = round(
        (
            sum(1.0 for row in density_rows_with_raw if bool(row.get("sanity_ok", False)))
            / max(1, len(density_rows_with_raw))
        ),
        4,
    )
    leader_semantic_quality_rate = round(
        sum(v0_v1_leader_quality_rows) / max(1, len(v0_v1_leader_quality_rows)),
        4,
    )
    dimension_semantic_quality_rate = round(
        sum(v0_v1_dimension_quality_rows) / max(1, len(v0_v1_dimension_quality_rows)),
        4,
    )
    packet_v0_v1_summary = SiteSchematicPacketV0V1Summary(
        packet_id=packet_v0_v1_summary_raw.packet_id,
        page_count=packet_v0_v1_summary_raw.page_count,
        modality_counts=packet_v0_v1_summary_raw.modality_counts,
        ambiguous_page_count=packet_v0_v1_summary_raw.ambiguous_page_count,
        primitive_count=packet_v0_v1_summary_raw.primitive_count,
        validated_primitive_count=packet_v0_v1_summary_raw.validated_primitive_count,
        leader_candidate_count=packet_v0_v1_summary_raw.leader_candidate_count,
        dimension_candidate_count=packet_v0_v1_summary_raw.dimension_candidate_count,
        modality_fail=packet_v0_v1_summary_raw.modality_fail,
        primitive_graph_fail=(
            packet_v0_v1_summary_raw.primitive_graph_fail
            or suspicious_zero_primitive_packet_failures > 0
        ),
    )
    grounded_statuses = Counter(row.status for row in all_grounded_symbols)
    family_counts = Counter(row.family for row in all_grounded_symbols if row.family)
    schematic_page_count = sum(
        1
        for row in pages
        if row.sheet_type in {
            "legend_symbol",
            "floorplan_overall",
            "floorplan_detail",
            "equipment_room_layout",
            "rack_detail",
            "riser_diagram",
            "installation_detail",
        }
    )
    packet_v2_summary = SiteSchematicPacketV2Summary(
        packet_id=packet_id_value,
        page_count=len(page_texts),
        candidate_symbol_count=len(all_symbol_candidate_groups),
        grounded_symbol_count=int(grounded_statuses.get("grounded", 0)),
        ambiguous_symbol_count=int(grounded_statuses.get("ambiguous", 0)),
        unresolved_symbol_count=int(grounded_statuses.get("unresolved", 0)),
        legend_dictionary_entry_count=len(all_legend_grounding_entries),
        family_counts=dict(family_counts),
        packet_level_fail=bool(
            schematic_page_count > 0
            and len(all_symbol_candidate_groups) == 0
        ),
    )
    hardpage_summary_raw = build_packet_hardpage_summary(
        packet_id=packet_id_value,
        page_rows=all_v2_page_rows,
    )
    required_hardpage_types = derive_required_hardpage_types(all_v2_page_rows)
    packet_v2_hardpage_summary = SiteSchematicPacketV2HardpageSummary(
        packet_id=hardpage_summary_raw.packet_id,
        required_page_types=tuple(required_hardpage_types),
        satisfied_page_types=tuple(hardpage_summary_raw.satisfied_page_types),
        hardpage_rate=round(hardpage_summary_raw.rate, 4),
    )
    page_type_by_index = {int(row.get("page_index", -1)): str(row.get("sheet_type", "")) for row in all_v2_page_rows}
    required_hardpage_set = set(required_hardpage_types)
    hardpage_candidate_total = sum(
        1
        for row in all_symbol_candidate_groups
        if page_type_by_index.get(row.page_index, "") in required_hardpage_set
    )
    hardpage_grounded_total = sum(
        1
        for row in all_grounded_symbols
        if row.status == "grounded" and page_type_by_index.get(row.page_index, "") in required_hardpage_set
    )
    expected_families = {
        row.family for row in all_legend_grounding_entries if row.family and row.family != "unknown_symbol_group"
    }
    grounded_families = {
        row.family for row in all_grounded_symbols if row.status == "grounded" and row.family and row.family != "unknown_symbol_group"
    }
    yield_metrics = compute_grounded_yield_metrics(
        total_candidates=len(all_symbol_candidate_groups),
        grounded_symbols=int(grounded_statuses.get("grounded", 0)),
        unresolved_symbols=int(grounded_statuses.get("unresolved", 0)),
        hardpage_candidates=hardpage_candidate_total,
        hardpage_grounded=hardpage_grounded_total,
        expected_family_total=max(1, len(expected_families)),
        expected_family_grounded=len(grounded_families & expected_families),
    )
    room_device_assoc_rows = [row for row in all_grounded_symbols if row.status != "unresolved"]
    room_device_assoc_rate = (
        sum(1.0 for row in room_device_assoc_rows if bool(row.metadata.get("room_device_association_ok", False)))
        / max(1, len(room_device_assoc_rows))
    )
    connector_quality_rows = [
        row for row in all_grounded_symbols if bool(row.metadata.get("connector_required", False)) and row.status != "unresolved"
    ]
    connector_quality_rate = (
        sum(1.0 for row in connector_quality_rows if bool(row.metadata.get("connector_grounding_ok", False)))
        / max(1, len(connector_quality_rows))
    )
    packet_v2_quality_summary = SiteSchematicPacketV2QualitySummary(
        packet_id=packet_id_value,
        grounded_symbol_yield_rate=round(yield_metrics.grounded_symbol_yield_rate, 4),
        hardpage_grounded_symbol_yield_rate=round(yield_metrics.hardpage_grounded_symbol_yield_rate, 4),
        unresolved_symbol_ratio=round(yield_metrics.unresolved_symbol_ratio, 4),
        room_device_association_rate=round(room_device_assoc_rate, 4),
        connector_grounding_quality_rate=round(connector_quality_rate, 4),
        expected_family_grounded_coverage_rate=round(yield_metrics.expected_family_grounded_coverage_rate, 4),
        hardpage_requirement_complete=bool(required_hardpage_types),
    )
    grounded_rows_for_audit = [
        {
            "grounding_state": row.metadata.get("grounding_state", row.status),
            "connector_grounding_ok": row.metadata.get("connector_grounding_ok", False),
            "room_device_association_ok": row.metadata.get("room_device_association_ok", False),
            "room_device_association_score": row.metadata.get("room_device_association_score", 0.0),
        }
        for row in all_grounded_symbols
    ]
    schema_required_types = list(required_hardpage_types)
    enforced_required_types = enforce_nonempty_required_hardpages(
        page_rows=all_v2_page_rows,
        schema_required_types=schema_required_types,
    )
    truth_audit = audit_packet_truth_signals(
        candidate_symbol_count=len(all_symbol_candidate_groups),
        grounded_symbol_count=int(grounded_statuses.get("grounded", 0)),
        unresolved_symbol_count=int(grounded_statuses.get("unresolved", 0)),
        connector_topology_candidate_rate=round(connector_quality_rate, 4),
        connector_grounding_quality_rate=round(connector_quality_rate, 4),
        room_device_association_rate=round(room_device_assoc_rate, 4),
        required_page_types=list(enforced_required_types),
        satisfied_page_types=list(packet_v2_hardpage_summary.satisfied_page_types),
        grounded_rows=grounded_rows_for_audit,
    )
    packet_v2_truth_audit_summary = SiteSchematicPacketV2TruthAuditSummary(
        packet_id=packet_id_value,
        truth_audit_reasons=tuple(truth_audit.reasons),
        suspicious_uniform_grounding=truth_audit.suspicious_uniform_grounding,
        impossible_connector_success=truth_audit.impossible_connector_success,
        impossible_room_assoc_success=truth_audit.impossible_room_assoc_success,
        empty_required_hardpage_set=(len(enforced_required_types) == 0 and len(all_v2_page_rows) > 0),
    )
    grounded_symbol_rows = [
        {
            "grounded_family": row.family,
            "grounding_state": row.metadata.get("grounding_state", row.status),
            "hardpage_page": page_type_by_index.get(row.page_index, "") in required_hardpage_set,
            "legend_match_score": row.metadata.get("legend_match_score", 0.0),
            "legend_text_association_score": row.metadata.get("legend_text_association_score", row.metadata.get("text_association_score", 0.0)),
            "connector_context_score": row.metadata.get("connector_context_score", 0.0),
            "room_device_association_score": row.metadata.get("room_device_association_score", 0.0),
            "page_type_compatibility": row.metadata.get("page_type_compatibility", 0.0),
            "connector_grounding_ok": bool(row.metadata.get("connector_grounding_ok", False)),
            "room_device_association_ok": bool(row.metadata.get("room_device_association_ok", False)),
            "near_room_label": bool(row.metadata.get("near_room_label", False)),
            "same_region": bool(row.metadata.get("same_region", False)),
            "leader_attached": bool(row.metadata.get("leader_attached", False)),
        }
        for row in all_grounded_symbols
    ]
    family_coverage = compute_family_coverage(
        expected_families=sorted(expected_families),
        grounded_families=[
            row["grounded_family"]
            for row in grounded_symbol_rows
            if row["grounded_family"] and row["grounding_state"] == "grounded"
        ],
        hardpage_grounded_families=[
            row["grounded_family"]
            for row in grounded_symbol_rows
            if row["grounded_family"] and row["grounding_state"] == "grounded" and bool(row["hardpage_page"])
        ],
    )
    hardpage_gate = enforce_hardpage_truth(
        required_page_types=list(enforced_required_types),
        satisfied_page_types=list(packet_v2_hardpage_summary.satisfied_page_types),
        hardpage_grounded_symbol_yield_rate=float(packet_v2_quality_summary.hardpage_grounded_symbol_yield_rate),
        hardpage_family_grounded_coverage_rate=float(family_coverage.hardpage_family_grounded_coverage_rate),
    )
    room_truth_hits = sum(1 for row in grounded_symbol_rows if row["room_device_association_ok"])
    connector_truth_hits = sum(1 for row in grounded_symbol_rows if row["connector_grounding_ok"])
    packet_v2_enforcement_summary = SiteSchematicPacketV2EnforcementSummary(
        packet_id=packet_id_value,
        expected_family_grounded_coverage_rate=round(family_coverage.expected_family_grounded_coverage_rate, 4),
        hardpage_family_grounded_coverage_rate=round(family_coverage.hardpage_family_grounded_coverage_rate, 4),
        room_device_evidence_truth_rate=round(room_truth_hits / max(1, len(grounded_symbol_rows)), 4),
        connector_evidence_truth_rate=round(connector_truth_hits / max(1, len(grounded_symbol_rows)), 4),
        hardpage_requirement_truth_rate=1.0 if hardpage_gate.hardpage_requirement_truth_ok else 0.0,
        hardpage_grounded_symbol_yield_rate=round(packet_v2_quality_summary.hardpage_grounded_symbol_yield_rate, 4),
    )
    packet_expected_families = derive_expected_families_from_packet_local_text(
        legend_texts=[str(row.raw_label or "") for row in all_legend_grounding_entries],
        outlet_definition_texts=[str(getattr(row, "description", "") or "") for row in outlet_type_definitions],
        abbreviation_texts=[
            f"{str(getattr(row, 'short_form', '') or '')} {str(getattr(row, 'meaning', '') or '')}".strip()
            for row in abbreviations
        ],
        page_titles=[str(row.get("sheet_title", row.get("sheet_type", ""))) for row in all_v2_page_rows],
        domain_default_families=sorted(expected_families),
    )
    required_page_types_v2_5 = derive_required_hardpages(
        page_rows=all_v2_page_rows,
        schema_required_types=list(enforced_required_types) if enforced_required_types else list(required_hardpage_types),
    )
    family_coverage_truth = compute_family_coverage_truth(
        packet_expected_families=packet_expected_families,
        grounded_families=[
            str(row["grounded_family"])
            for row in grounded_symbol_rows
            if row["grounded_family"] and row["grounding_state"] in {"grounded", "ambiguous"}
        ],
        hardpage_expected_families=packet_expected_families,
        hardpage_grounded_families=[
            str(row["grounded_family"])
            for row in grounded_symbol_rows
            if row["grounded_family"] and row["grounding_state"] in {"grounded", "ambiguous"} and bool(row["hardpage_page"])
        ],
    )
    hardpage_gate_v2_5 = enforce_v2_5_hardpage_gate(
        required_page_types=required_page_types_v2_5,
        hardpage_grounded_symbol_yield_rate=float(packet_v2_quality_summary.hardpage_grounded_symbol_yield_rate),
        hardpage_family_grounded_coverage_rate=float(family_coverage_truth.hardpage_family_grounded_coverage_rate),
    )
    packet_v2_family_coverage_summary = SiteSchematicPacketV2FamilyCoverageSummary(
        packet_id=packet_id_value,
        packet_expected_families=tuple(sorted(family_coverage_truth.packet_expected_families)),
        grounded_families=tuple(sorted(family_coverage_truth.grounded_families)),
        hardpage_expected_families=tuple(sorted(family_coverage_truth.hardpage_expected_families)),
        hardpage_grounded_families=tuple(sorted(family_coverage_truth.hardpage_grounded_families)),
        expected_family_grounded_coverage_rate=round(family_coverage_truth.expected_family_grounded_coverage_rate, 4),
        hardpage_family_grounded_coverage_rate=round(family_coverage_truth.hardpage_family_grounded_coverage_rate, 4),
    )
    return SiteSchematicBundle(
        source_modality=source_modality,
        page_count=len(page_texts),
        typed_pages=typed_pages,
        overlay_counts=dict(overlay_counter),
        sheet_type_counts=dict(sheet_counter),
        observation_counts=dict(observation_counter),
        pages=tuple(pages),
        observations=tuple(observations),
        page_observations=tuple(page_observations),
        page_modality_decisions=tuple(page_modality_decisions),
        page_sections=tuple(page_sections),
        vector_primitives=tuple(all_vector_primitives),
        vector_primitive_validations=tuple(all_vector_primitive_validations),
        vector_primitive_graphs=tuple(all_vector_primitive_graphs),
        measurement_candidates=tuple(all_measurement_candidates),
        packet_v0_v1_summary=packet_v0_v1_summary,
        symbol_candidate_groups=tuple(all_symbol_candidate_groups),
        legend_grounding_entries=tuple(all_legend_grounding_entries),
        grounded_symbols=tuple(all_grounded_symbols),
        packet_v2_summary=packet_v2_summary,
        packet_v2_hardpage_summary=packet_v2_hardpage_summary,
        packet_v2_quality_summary=packet_v2_quality_summary,
        packet_v2_truth_audit_summary=packet_v2_truth_audit_summary,
        packet_v2_enforcement_summary=packet_v2_enforcement_summary,
        packet_v2_family_coverage_summary=packet_v2_family_coverage_summary,
        universal_tables=tuple(all_universal_tables),
        regions=tuple(all_regions),
        detail_regions=tuple(all_detail_regions),
        subregions=tuple(all_subregions),
        pseudo_pages=tuple(all_pseudo_pages),
        scoped_note_links=tuple(all_scoped_note_links),
        legend_entries=tuple(legend_entries),
        outlet_type_definitions=tuple(outlet_type_definitions),
        abbreviations=tuple(abbreviations),
        drawing_index_rows=tuple(drawing_index_row_objects),
        semantic_lineage_refs=tuple(semantic_lineage_refs),
        note_clauses_structured=tuple(note_clause_objects),
        mounting_rules=tuple(mounting_rules),
        termination_rules=tuple(termination_rules),
        color_conventions=tuple(color_conventions),
        environmental_requirements=tuple(environmental_requirements),
        grounding_requirements=tuple(grounding_requirements),
        testing_requirements=tuple(testing_requirements),
        labeling_requirements=tuple(labeling_requirements),
        responsibility_assignments=tuple(responsibility_assignments),
        cable_rules=tuple(cable_rules),
        pathway_rules=tuple(pathway_rules),
        service_loop_requirements=tuple(service_loop_requirements),
        device_instances=tuple(all_device_instances),
        outlet_instances=tuple(all_outlet_instances),
        rooms=tuple(all_rooms),
        closets=tuple(all_closets),
        racks=tuple(all_racks),
        riser_edges=tuple(all_riser_edges),
        topology_segments=tuple(all_topology_segments),
        topology_endpoints=tuple(all_topology_endpoints),
        topology_relations=tuple(all_topology_relations),
        symbol_instances=tuple(all_symbol_instances),
        symbol_links=tuple(all_symbol_links),
        symbol_resolution_outcomes=tuple(all_symbol_resolution_outcomes),
        symbol_candidate_inputs=tuple(all_symbol_candidate_inputs),
        reasoning_findings=reasoning_findings,
        consistency_checks=consistency_checks,
        contradiction_flags=contradiction_flags,
        anchor_reconciliation_suggestions=anchor_reconciliation_suggestions,
        topology_review_suggestions=topology_review_suggestions,
        packet_reasoning_summary=packet_reasoning_summary,
        family_consistency_summaries=family_consistency_summaries,
        review_queue_summary=review_queue_summary,
        topology_coverage_summary=topology_coverage_summary,
        profile_qa_summaries=profile_qa_summaries,
        graph=graph,
        model_registry={
            **dict(model_registry),
            "observation_diagnostics": observation_diagnostics,
            "phase_v0_v1": {
                "page_modality": [row.to_dict() for row in page_modality_decisions],
                "vector_primitive_count": len(all_vector_primitives),
                "vector_validated_primitive_count": sum(1 for row in all_vector_primitive_validations if row.valid),
                "vector_graph_count": len(all_vector_primitive_graphs),
                "measurement_candidate_count": len(all_measurement_candidates),
                "modality_counts": dict(Counter(row.modality for row in page_modality_decisions)),
                "ambiguous_page_count": sum(1 for row in page_modality_decisions if row.ambiguous),
                "vector_pages": sorted({row.page_index for row in all_vector_primitives}),
                "vector_leader_candidate_total": int(
                    sum(len(row.leader_candidate_ids) for row in all_vector_primitive_graphs)
                ),
                "vector_dimension_candidate_total": int(
                    sum(len(row.dimension_candidate_ids) for row in all_vector_primitive_graphs)
                ),
                "suspicious_zero_primitive_page_failures": suspicious_zero_primitive_page_failures,
                "suspicious_zero_primitive_packet_failures": suspicious_zero_primitive_packet_failures,
                "primitive_dedup_effectiveness_rate": primitive_dedup_effectiveness_rate,
                "primitive_density_sanity_rate": primitive_density_sanity_rate,
                "leader_semantic_quality_rate": leader_semantic_quality_rate,
                "dimension_semantic_quality_rate": dimension_semantic_quality_rate,
                "density_audit_rows": v0_v1_density_audit_rows,
                "zero_guard_rows": v0_v1_zero_guard_rows,
                "packet_summary": packet_v0_v1_summary.to_dict(),
            },
            "phase_v2": {
                "candidate_symbol_count": len(all_symbol_candidate_groups),
                "candidate_symbol_total": len(all_symbol_candidate_groups),
                "grounded_symbol_count": len(all_grounded_symbols),
                "grounded_symbol_total": int(grounded_statuses.get("grounded", 0)),
                "unresolved_symbol_total": int(grounded_statuses.get("unresolved", 0)),
                "hardpage_candidate_symbol_total": hardpage_candidate_total,
                "hardpage_grounded_symbol_total": hardpage_grounded_total,
                "expected_family_total": max(1, len(expected_families)),
                "expected_family_grounded": len(grounded_families & expected_families),
                "legend_grounding_entry_count": len(all_legend_grounding_entries),
                "page_rows": all_v2_page_rows,
                "schema_required_types": schema_required_types,
                "status_counts": {
                    "grounded": sum(1 for row in all_grounded_symbols if row.status == "grounded"),
                    "ambiguous": sum(1 for row in all_grounded_symbols if row.status == "ambiguous"),
                    "unresolved": sum(1 for row in all_grounded_symbols if row.status == "unresolved"),
                },
                "family_counts": dict(Counter(row.family for row in all_grounded_symbols if row.family)),
                "packet_summary": packet_v2_summary.to_dict(),
            },
            "phase_v2_1": {
                "packet_hardpage_summary": packet_v2_hardpage_summary.to_dict(),
            },
            "phase_v2_2": {
                "packet_quality_summary": packet_v2_quality_summary.to_dict(),
            },
            "phase_v2_3": {
                "truth_audit_summary": packet_v2_truth_audit_summary.to_dict(),
            },
            "phase_v2_4": {
                "enforcement_summary": packet_v2_enforcement_summary.to_dict(),
                "grounding_sample_rows": select_grounding_sample_rows(grounded_symbol_rows, limit=25),
                "hardpage_requirement_truth_reasons": list(hardpage_gate.reasons),
            },
            "phase_v2_5": {
                "family_coverage_summary": packet_v2_family_coverage_summary.to_dict(),
                "required_page_types": list(required_page_types_v2_5),
                "hardpage_gate_ok": hardpage_gate_v2_5.ok,
                "hardpage_gate_reasons": list(hardpage_gate_v2_5.reasons),
            },
            "universal_table_contract": {
                "contract_version": "2026-04-12.v1",
                "table_count": len(all_universal_tables),
                "semantic_lineage_ref_count": len(semantic_lineage_refs),
                "table_kind_counts": dict(Counter(row.table_kind for row in all_universal_tables)),
            },
            "symbol_stage_prep": {
                "contract_version": "symbol_input_v1",
                "symbol_candidate_inputs": len(all_symbol_candidate_inputs),
                "symbol_resolution_outcomes": len(all_symbol_resolution_outcomes),
                "status_counts": {
                    "linked": sum(1 for row in all_symbol_resolution_outcomes if row.status == "linked"),
                    "weakly_linked": sum(1 for row in all_symbol_resolution_outcomes if row.status == "weakly_linked"),
                    "unresolved": sum(1 for row in all_symbol_resolution_outcomes if row.status == "unresolved"),
                    "conflicting": sum(1 for row in all_symbol_resolution_outcomes if row.status == "conflicting"),
                    "legend_defined_but_unused": sum(1 for row in all_symbol_resolution_outcomes if row.status == "legend_defined_but_unused"),
                    "detected_but_unmapped": sum(1 for row in all_symbol_resolution_outcomes if row.status == "detected_but_unmapped"),
                    "candidate_requires_review": sum(1 for row in all_symbol_resolution_outcomes if row.status == "candidate_requires_review"),
                },
            },
            "symbol_model_adapter": model_adapter_diag,
            "section_detector": {
                "mode": section_detector_mode,
                "pdf_source_path_present": bool(source_path and source_path.suffix.lower() == ".pdf"),
                "pages_with_sections": sorted({row.page_index for row in page_sections}),
                "page_sections_total": len(page_sections),
                "standalone_detector_supported": False,
            },
            "symbol_detector_runtime": {
                "heuristic_only_detector": heuristic_only_detector,
                "model_prediction_pages": sorted(model_detections_by_page.keys()),
            },
            "symbol_grounding_strengthening": {
                "strengthened_anchor_count": sum(grounding_strengthened_by_profile.values()),
                "strengthened_by_profile": dict(grounding_strengthened_by_profile),
                "strengthened_by_family": dict(grounding_strengthened_by_family),
                "strengthened_samples": grounding_strengthened_samples,
                "rejected_samples": grounding_rejected_samples,
            },
            "topology_parsing": {
                "topology_endpoints": len(all_topology_endpoints),
                "topology_relations": len(all_topology_relations),
                "profile_endpoint_counts": dict(topology_profile_endpoint_counts),
                "profile_relation_counts": dict(topology_profile_relation_counts),
                "profile_abstain_counts": dict(topology_profile_abstain_counts),
                "endpoint_bridge_promotions": dict(topology_endpoint_bridge_promotions),
                "promoted_endpoint_samples": topology_promoted_endpoint_samples,
            },
            "graph_reasoning": dict(reasoning_diagnostics),
            "graph_reasoning_summary": {
                "packet_reasoning_summary": packet_reasoning_summary.to_dict(),
                "review_queue_summary": review_queue_summary.to_dict(),
                "topology_coverage_summary": topology_coverage_summary.to_dict(),
                "family_consistency_summaries": [row.to_dict() for row in family_consistency_summaries[:24]],
                "profile_qa_summaries": [row.to_dict() for row in profile_qa_summaries[:24]],
            },
        },
    )
