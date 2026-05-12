from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from orbitbrief_core.parser.site_schematic.column_structure_fusion import (
    classify_note_scope_with_columns,
    infer_holdout_columns,
)
from orbitbrief_core.parser.site_schematic.global_note_guard import is_strong_global_note
from orbitbrief_core.parser.site_schematic.locality_scope_closure import close_locality_scope_if_strong
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicDetailRegion,
    SiteSchematicPageObservation,
    SiteSchematicPseudoPage,
    SiteSchematicRegion,
    SiteSchematicScopedNoteLink,
    SiteSchematicSubregion,
    SiteSchematicUniversalTable,
)
from orbitbrief_core.parser.site_schematic.region_bbox_completion import (
    complete_region_bbox_from_children,
    ensure_locality_provenance,
)
from orbitbrief_core.parser.site_schematic.structure_graph_locality import infer_note_scope_with_structure_graph

_NOTE_LINE_RE = re.compile(r"(?m)^\s*(?:\d+\.|[A-Z]\.|[-*])\s+.*$")
_DRAWING_ROW_RE = re.compile(r"(?m)^\s*(?:T|TC)\d{3}(?:\.\d+)?\s+.*$")
_ABBREV_LINE_RE = re.compile(r"(?m)^\s*[A-Z][A-Z0-9./()'\"#&+_-]{1,24}\s*(?:-|=|:)\s+.*$")
_DETAIL_HEADER_RE = re.compile(
    r"(?i)\b(?:detail|typical|elevation|section|diagram|riser|grounding|rack|cabinet|guestroom|layout|callout|keyed note)\b"
)
_DETAIL_TOKEN_RE = re.compile(r"(?i)\b(?:detail|typical)\s+[A-Z0-9]+\b")
_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("equipment_elevation", re.compile(r"(?i)\b(?:elevation|rack|cabinet|busbar|patch panel|110 block|ladder rack)\b")),
    ("riser_diagram_fragment", re.compile(r"(?i)\b(?:riser|homerun|tmgb|tgb|ground|conduit|pull box|weatherhead)\b")),
    ("legend_table_box", re.compile(r"(?i)\b(?:legend|symbol|abbreviation|schedule|table)\b")),
    ("general_notes_block", re.compile(r"(?i)\b(?:general notes|notes|keyed notes?)\b")),
    ("mini_floorplan", re.compile(r"(?i)\b(?:floor plan|plan|guestroom|room|corridor|office|conference)\b")),
    ("detail_note_block", re.compile(r"(?i)\b(?:detail note|typical detail|mounting|termination|labeling|testing)\b")),
)
_NOTE_TARGET_RE = re.compile(r"(?i)\b(?:detail|typ\.?)\s*([A-Z0-9-]{1,8})\b")
_SECTION_HEADER_RE = re.compile(r"(?i)^[A-Z0-9][A-Z0-9\s/&().,'-]{4,}$")
_NOTE_HEADER_HINTS = (
    "general notes",
    "horizontal cabling",
    "junction box",
    "conduit notes",
    "legend notes",
    "notes",
    "specifications",
    "requirements",
)
_TABLE_KIND_TO_REGION_KIND = {
    "drawing_index": "drawing_index_block",
    "abbreviation_matrix": "abbreviation_block",
    "symbol_legend": "symbol_legend_block",
    "outlet_definition": "outlet_definition_block",
    "responsibility_matrix": "responsibility_matrix_block",
    "embedded_detail_schedule": "embedded_schedule_block",
    "component_spec": "notes_section_block",
    "manufacturer_part_table": "notes_section_block",
}
_PHASEC_REQUIRED_REGION_KINDS: dict[str, tuple[str, ...]] = {
    "TC001": (
        "title_block",
        "revision_block",
        "abbreviation_block",
        "drawing_index_block",
        "symbol_legend_block",
        "outlet_definition_block",
        "general_notes_block",
        "horizontal_cabling_notes_block",
        "junction_box_conduit_notes_block",
    ),
    "T000": ("title_block", "notes_spec_column", "drawing_index_block", "notes_section_block"),
    "T001": (
        "responsibility_matrix_block",
        "structured_cabling_legend_block",
        "intrusion_legend_block",
        "access_intercom_legend_block",
        "cctv_legend_block",
        "legend_notes_block",
    ),
    "T700": ("detail_frame", "pseudo_page", "local_detail_note_block"),
    "T900": (
        "equipment_room_plan_block",
        "rack_elevation_block",
        "grounding_riser_block",
        "embedded_schedule_block",
        "local_detail_note_block",
    ),
    "T901": ("riser_body_block", "riser_callout_block", "detail_inset_block"),
    "T905": ("detail_frame", "embedded_schedule_block", "local_detail_note_block"),
    "T906": ("detail_frame", "pathway_support_block", "local_detail_note_block"),
    "TC502": ("detail_frame", "detail_note_block"),
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _line_bbox(start: int, end: int, total: int, *, x0: float, x1: float) -> tuple[float, float, float, float]:
    total = max(total, 1)
    y0 = max(0.0, min(1.0, start / total))
    y1 = max(y0, min(1.0, end / total))
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


def _region(region_id: str, page_index: int, kind: str, text: str, confidence: float, bbox: tuple[float, float, float, float], *, source_mode: str = "text_heuristic", metadata: dict | None = None) -> SiteSchematicRegion:
    return SiteSchematicRegion(
        region_id=region_id,
        page_index=page_index,
        kind=kind,
        text=_clean(text),
        confidence=confidence,
        bbox=bbox,
        source_mode=source_mode,
        metadata=metadata or {},
    )


def _slice_lines(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start:end]).strip()


def _matching_line_indices(lines: Iterable[str], pattern: re.Pattern[str]) -> list[int]:
    return [idx for idx, line in enumerate(lines) if pattern.search(line)]


def _region_line_bbox(
    parent_bbox: tuple[float, float, float, float] | None,
    start: int,
    end: int,
    total: int,
) -> tuple[float, float, float, float] | None:
    if parent_bbox is None:
        return None
    px0, py0, px1, py1 = parent_bbox
    span = max(1e-6, py1 - py0)
    y0 = py0 + span * (max(start, 0) / max(total, 1))
    y1 = py0 + span * (max(end, start + 1) / max(total, 1))
    return (round(px0, 4), round(y0, 4), round(px1, 4), round(min(py1, y1), 4))


def _bbox_or_none(value: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    if isinstance(value, tuple) and len(value) == 4:
        return value
    return None


def _union_bbox(
    existing: tuple[float, float, float, float] | None,
    incoming: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    current = _bbox_or_none(existing)
    new = _bbox_or_none(incoming)
    if current is None:
        return new
    if new is None:
        return current
    x0 = min(current[0], new[0])
    y0 = min(current[1], new[1])
    x1 = max(current[2], new[2])
    y1 = max(current[3], new[3])
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


def _fallback_bbox_from_regions(regions: tuple[SiteSchematicRegion, ...]) -> tuple[float, float, float, float] | None:
    bbox = None
    for region in regions:
        bbox = _union_bbox(bbox, region.bbox)
    return bbox


def _table_kind_to_region_kind(*, table_kind: str, sheet_number: str, table_text: str) -> str:
    normalized = table_kind.strip().lower()
    if normalized in _TABLE_KIND_TO_REGION_KIND:
        return _TABLE_KIND_TO_REGION_KIND[normalized]
    body = table_text.lower()
    if "legend" in body and "cctv" in body:
        return "cctv_legend_block"
    if "legend" in body and ("intrusion" in body or "ids" in body):
        return "intrusion_legend_block"
    if "legend" in body and ("access" in body or "intercom" in body):
        return "access_intercom_legend_block"
    if "structured cabling" in body:
        return "structured_cabling_legend_block"
    if "riser" in body or "ground" in body:
        return "grounding_riser_block" if sheet_number == "T900" else "riser_body_block"
    if "rack" in body or "elevation" in body:
        return "rack_elevation_block"
    return "generic_grid_block"


def _header_hint_kind(text: str) -> str | None:
    lowered = text.lower().strip()
    if not lowered:
        return None
    if "general notes" in lowered:
        return "general_notes_block"
    if "horizontal cabling" in lowered:
        return "horizontal_cabling_notes_block"
    if "junction box" in lowered or "conduit" in lowered:
        return "junction_box_conduit_notes_block"
    if "legend notes" in lowered:
        return "legend_notes_block"
    if "notes" in lowered or "spec" in lowered or "requirement" in lowered:
        return "notes_section_block"
    return None


def _region_for_table(
    *,
    page_index: int,
    table: SiteSchematicUniversalTable,
    sheet_number: str,
) -> SiteSchematicRegion:
    region_kind = _table_kind_to_region_kind(
        table_kind=table.table_kind,
        sheet_number=sheet_number,
        table_text="\n".join(row.raw_text_joined for row in table.rows if row.raw_text_joined),
    )
    metadata = {
        "sheet_number": sheet_number,
        "source_table_ids": [table.table_id],
        "table_kind": table.table_kind,
        "phasec_anchor": "universal_table",
    }
    table_text = "\n".join(cell.raw_text for row in table.rows for cell in row.cells if cell.raw_text).strip()
    return SiteSchematicRegion(
        region_id=f"p{page_index}:phasec:{region_kind}:{table.table_id}",
        page_index=page_index,
        kind=region_kind,
        text=_clean(table_text) or f"{table.table_kind} table",
        confidence=max(0.6, float(table.confidence)),
        bbox=table.bbox,
        source_mode="table_anchor_phasec",
        metadata=metadata,
    )


def _phasec_kind_overrides_for_sheet(*, sheet_number: str, kind: str, text: str) -> str:
    lowered = text.lower()
    if sheet_number == "T001":
        if "structured cabling" in lowered:
            return "structured_cabling_legend_block"
        if "intrusion" in lowered:
            return "intrusion_legend_block"
        if "access" in lowered or "intercom" in lowered:
            return "access_intercom_legend_block"
        if "cctv" in lowered or "camera" in lowered:
            return "cctv_legend_block"
        if "notes" in lowered:
            return "legend_notes_block"
    if sheet_number == "T900":
        if "riser" in lowered or "ground" in lowered:
            return "grounding_riser_block"
        if "rack" in lowered or "elevation" in lowered:
            return "rack_elevation_block"
        if "equipment room" in lowered or "mdf" in lowered or "idf" in lowered:
            return "equipment_room_plan_block"
    if sheet_number == "T901":
        if "riser" in lowered:
            return "riser_body_block"
        if "detail" in lowered or "inset" in lowered:
            return "detail_inset_block"
        if "callout" in lowered or "note" in lowered:
            return "riser_callout_block"
    if sheet_number in {"T700", "T905", "T906", "TC502"} and kind in {"detail_block", "plan_body_block"}:
        return "detail_frame"
    return kind


def _cluster_subregions_for_pseudo_pages(
    subregions: tuple[SiteSchematicSubregion, ...],
    *,
    max_clusters: int,
) -> tuple[tuple[int, tuple[SiteSchematicSubregion, ...]], ...]:
    if not subregions:
        return ()
    indexed = list(enumerate(subregions, start=1))
    indexed.sort(
        key=lambda row: (
            row[1].bbox[1] if row[1].bbox else 1e12,
            row[1].bbox[0] if row[1].bbox else 1e12,
            row[0],
        )
    )
    clusters: list[list[tuple[int, SiteSchematicSubregion]]] = []
    for item in indexed:
        idx, sub = item
        sb = sub.bbox
        assigned = False
        for cluster in clusters:
            anchor = cluster[-1][1]
            ab = anchor.bbox
            same_role = sub.role == anchor.role
            if sb is None or ab is None:
                if same_role:
                    cluster.append(item)
                    assigned = True
                    break
                continue
            y_gap = sb[1] - ab[3]
            x_delta = abs(sb[0] - ab[0])
            overlap = min(sb[3], ab[3]) - max(sb[1], ab[1])
            if same_role and (overlap >= -0.015 or (y_gap <= 0.055 and x_delta <= 0.18)):
                cluster.append(item)
                assigned = True
                break
        if not assigned:
            clusters.append([item])
    if len(clusters) <= max_clusters:
        return tuple((idx, tuple(row for _, row in cluster)) for idx, cluster in enumerate(clusters, start=1))
    while len(clusters) > max_clusters:
        left = clusters[-2]
        right = clusters[-1]
        left.extend(right)
        clusters.pop()
    return tuple((idx, tuple(row for _, row in cluster)) for idx, cluster in enumerate(clusters, start=1))


def _text_has_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def classify_subregion_role(*, text: str, sheet_type: str, parent_kind: str = "") -> str:
    body = text or ""
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(body):
            return role
    if sheet_type in {"riser_diagram"}:
        return "riser_diagram_fragment"
    if sheet_type in {"equipment_room_layout", "rack_detail"}:
        return "equipment_elevation"
    if parent_kind == "plan_body_block":
        return "mini_floorplan"
    return "detail_note_block"


def _is_global_note_text(text: str) -> bool:
    lowered = (text or "").lower()
    if (
        "general notes" in lowered
        or "general note" in lowered
        or "keyed notes" in lowered
        or "keyed note" in lowered
        or "project requirement" in lowered
    ):
        return True
    note_line_count = len(_NOTE_LINE_RE.findall(text or ""))
    if note_line_count >= 2 and len((text or "").split()) >= 12:
        return True
    return False


def build_nested_detail_regions(
    *,
    page_index: int,
    text: str,
    regions: tuple[SiteSchematicRegion, ...],
    sheet_type: str,
    page_observation: SiteSchematicPageObservation | None = None,
) -> tuple[SiteSchematicDetailRegion, ...]:
    rows: list[SiteSchematicDetailRegion] = []
    parent_lookup = {region.region_id: region for region in regions}
    mixed_detail_sheet_types = {"floorplan_detail", "equipment_room_layout", "installation_detail", "rack_detail", "riser_diagram"}
    if page_observation is not None and page_observation.layout_blocks and sheet_type in mixed_detail_sheet_types:
        parent = next((region for region in regions if region.kind in {"detail_block", "plan_body_block"}), None)
        parent_region_id = parent.region_id if parent else (regions[0].region_id if regions else "")
        obs_idx = 0
        candidates = sorted(page_observation.layout_blocks, key=lambda row: row.confidence, reverse=True)[:18]
        for block in candidates:
            block_text = _clean(block.text)
            if not block_text:
                continue
            if block.role == "table":
                continue
            if block.confidence < 0.7:
                continue
            if not (
                _DETAIL_HEADER_RE.search(block_text)
                or _DETAIL_TOKEN_RE.search(block_text)
                or _text_has_any(block_text, ("guestroom", "layout", "elevation", "riser", "ground", "note", "rack"))
            ):
                continue
            obs_idx += 1
            rows.append(
                SiteSchematicDetailRegion(
                    detail_region_id=f"detail:p{page_index}:obs:{obs_idx}",
                    page_index=page_index,
                    parent_region_id=parent_region_id,
                    kind="detail_region",
                    text=block_text,
                    confidence=min(0.97, max(0.55, float(block.confidence))),
                    bbox=_bbox_or_none(block.bbox),
                    source_mode=block.source_mode or "model_assisted",
                    metadata={
                        "sheet_type": sheet_type,
                        "parent_kind": parent_lookup.get(parent_region_id).kind if parent_region_id in parent_lookup else "",
                        "provider": block.provider,
                    },
                )
            )
    for parent_idx, region in enumerate(regions, start=1):
        if region.kind not in {"detail_block", "plan_body_block"}:
            continue
        body = region.text.strip()
        if not body:
            continue
        # Region text is normalized upstream; segment by repeated detail headers first.
        segments: list[str] = []
        token_spans = [match.span() for match in _DETAIL_TOKEN_RE.finditer(body)]
        if len(token_spans) >= 2:
            starts = [span[0] for span in token_spans]
            starts.append(len(body))
            for start, end in zip(starts[:-1], starts[1:]):
                piece = body[start:end].strip(" -;,.")
                if piece:
                    segments.append(piece)
        elif len(token_spans) == 1:
            start = token_spans[0][0]
            leading = body[:start].strip(" -;,.")
            trailing = body[start:].strip(" -;,.")
            if leading:
                segments.append(leading)
            if trailing:
                segments.append(trailing)
        else:
            chunks = re.split(r"(?i)\s+(?=(?:detail|elevation|riser|grounding)\b)", body)
            for chunk in chunks:
                cleaned = chunk.strip(" -;,.")
                if cleaned:
                    segments.append(cleaned)
        if not segments:
            segments = [body]
        local_count = 0
        for idx, chunk in enumerate(segments):
            if not chunk:
                continue
            local_count += 1
            rows.append(
                SiteSchematicDetailRegion(
                    detail_region_id=f"detail:p{page_index}:r{parent_idx}:{local_count}",
                    page_index=page_index,
                    parent_region_id=region.region_id,
                    kind="detail_region",
                    text=chunk,
                    confidence=min(0.92, max(0.52, region.confidence + 0.1)),
                    bbox=_region_line_bbox(region.bbox, idx, idx + 1, len(segments)),
                    source_mode="text_nested_heuristic",
                    metadata={"sheet_type": sheet_type, "parent_kind": region.kind},
                )
            )
    deduped: list[SiteSchematicDetailRegion] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.parent_region_id, row.text.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return tuple(deduped)


def build_pseudo_pages(
    *,
    page_index: int,
    sheet_type: str,
    text: str,
    regions: tuple[SiteSchematicRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    page_observation: SiteSchematicPageObservation | None = None,
) -> tuple[SiteSchematicPseudoPage, ...]:
    rows: list[SiteSchematicPseudoPage] = []
    if subregions:
        lightweight_used = bool(page_observation and page_observation.metadata.get("lightweight_layout_used"))
        mixed_detail_sheet = sheet_type in {"equipment_room_layout", "installation_detail", "rack_detail", "floorplan_detail"}
        note_roles = {"general_notes_block", "detail_note_block"}
        if mixed_detail_sheet:
            global_notes = [row for row in subregions if row.role in note_roles and _is_global_note_text(row.text)]
            local_subregions = tuple(row for row in subregions if row not in global_notes)
        else:
            global_notes = []
            local_subregions = subregions
        clustering_applied = sheet_type in {"equipment_room_layout", "installation_detail", "rack_detail", "floorplan_detail"} or (
            sheet_type == "legend_symbol" and lightweight_used
        )
        clusters: tuple[tuple[int, tuple[SiteSchematicSubregion, ...]], ...]
        if clustering_applied:
            if sheet_type == "legend_symbol":
                max_clusters = 5
            elif lightweight_used:
                max_clusters = 6
            else:
                max_clusters = 8
            clusters = _cluster_subregions_for_pseudo_pages(local_subregions, max_clusters=max_clusters)
        else:
            clusters = tuple((idx, (subregion,)) for idx, subregion in enumerate(local_subregions, start=1))
        for idx, cluster in clusters:
            subregion = cluster[0]
            merged_text = " ".join(item.text for item in cluster if item.text).strip()
            merged_bbox = subregion.bbox
            for item in cluster[1:]:
                merged_bbox = _union_bbox(merged_bbox, item.bbox)
            dominant_role = max(
                (item.role for item in cluster),
                key=lambda role: sum(1 for row in cluster if row.role == role),
                default=subregion.role,
            )
            rows.append(
                SiteSchematicPseudoPage(
                    pseudo_page_id=f"pseudo:p{page_index}:{idx}",
                    page_index=page_index,
                    parent_region_id=subregion.parent_region_id,
                    detail_region_id=subregion.detail_region_id,
                    subregion_id=subregion.subregion_id,
                    role=dominant_role,
                    text=merged_text or subregion.text,
                    confidence=max(row.confidence for row in cluster),
                    bbox=merged_bbox,
                    source_mode=subregion.source_mode,
                    metadata={
                        "sheet_type": sheet_type,
                        "cluster_size": len(cluster),
                        "clustering_applied": clustering_applied,
                        "global_note_cluster": False,
                    },
                )
            )
        if global_notes:
            anchor = global_notes[0]
            merged_bbox = anchor.bbox
            merged_text = " ".join(row.text for row in global_notes if row.text).strip()
            for row in global_notes[1:]:
                merged_bbox = _union_bbox(merged_bbox, row.bbox)
            rows.append(
                SiteSchematicPseudoPage(
                    pseudo_page_id=f"pseudo:p{page_index}:global_notes",
                    page_index=page_index,
                    parent_region_id=anchor.parent_region_id,
                    detail_region_id=anchor.detail_region_id,
                    subregion_id=anchor.subregion_id,
                    role="general_notes_block",
                    text=merged_text or anchor.text,
                    confidence=max(row.confidence for row in global_notes),
                    bbox=merged_bbox,
                    source_mode=anchor.source_mode,
                    metadata={
                        "sheet_type": sheet_type,
                        "cluster_size": len(global_notes),
                        "clustering_applied": True,
                        "global_note_cluster": True,
                    },
                )
            )
        return tuple(rows)
    # Backstop: keep one pseudo-page over the dominant parse region.
    parent = next((region for region in regions if region.kind in {"detail_block", "plan_body_block"}), None)
    if parent is None and page_observation is not None and page_observation.layout_blocks:
        for idx, block in enumerate(page_observation.layout_blocks, start=1):
            if not _clean(block.text):
                continue
            rows.append(
                SiteSchematicPseudoPage(
                    pseudo_page_id=f"pseudo:p{page_index}:obs:{idx}",
                    page_index=page_index,
                    parent_region_id="",
                    detail_region_id="",
                    subregion_id="",
                    role=classify_subregion_role(text=block.text, sheet_type=sheet_type),
                    text=block.text,
                    confidence=max(0.45, float(block.confidence)),
                    bbox=_bbox_or_none(block.bbox),
                    source_mode=block.source_mode or "model_assisted",
                    metadata={"sheet_type": sheet_type, "provider": block.provider, "fallback": True},
                )
            )
        if rows:
            return tuple(rows)
    rows.append(
        SiteSchematicPseudoPage(
            pseudo_page_id=f"pseudo:p{page_index}:1",
            page_index=page_index,
            parent_region_id=parent.region_id if parent else "",
            detail_region_id="",
            subregion_id="",
            role="page_default",
            text=parent.text if parent else text,
            confidence=0.55 if parent is None else parent.confidence,
            bbox=parent.bbox if parent else None,
            source_mode="text_nested_heuristic",
            metadata={"sheet_type": sheet_type, "fallback": True},
        )
    )
    return tuple(rows)


def resolve_note_scope(
    *,
    page_index: int,
    note_clauses: tuple[str, ...],
    regions: tuple[SiteSchematicRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...],
    page_observation: SiteSchematicPageObservation | None = None,
    structure_graph: object | None = None,
) -> tuple[SiteSchematicScopedNoteLink, ...]:
    links: list[SiteSchematicScopedNoteLink] = []
    subregion_index = {sub.subregion_id: sub for sub in subregions}
    column_regions = tuple(
        region
        for region in regions
        if region.kind in {"notes_spec_column", "notes_section_block", "legend_notes_block"}
    )
    strongest_local_pseudos = tuple(
        pseudo.pseudo_page_id
        for pseudo in pseudo_pages
        if pseudo.role in {"equipment_elevation", "riser_diagram_fragment", "detail_note_block", "mini_floorplan"}
    )
    holdout_column_lanes: tuple = ()
    if page_observation is not None and page_observation.layout_blocks:
        notes_like = [
            row
            for row in page_observation.layout_blocks
            if row.bbox is not None and row.text and (row.role in {"text", "paragraph", "heading"} or len(row.text.split()) >= 6)
        ]
        if notes_like:
            width_guess = max((float(row.bbox[2]) for row in notes_like if row.bbox is not None), default=1.0)
            holdout_column_lanes = tuple(infer_holdout_columns(notes_like, page_width=max(1.0, width_guess)))
    for idx, note in enumerate(note_clauses, start=1):
        lowered = note.lower()
        graph_scope_level = ""
        graph_scope_targets: tuple[str, ...] = ()
        graph_parent_region_id = ""
        graph_pseudo_page_id = ""
        graph_confidence = 0.0
        graph_reasons: list[str] = []
        if structure_graph is not None:
            candidate_block_id = ""
            snippet = lowered[:56]
            for node in getattr(structure_graph, "nodes", ()):
                node_text = str((getattr(node, "metadata", {}) or {}).get("text", "")).lower()
                if snippet and snippet[:24] in node_text:
                    candidate_block_id = getattr(node, "node_id", "")
                    break
            decision = infer_note_scope_with_structure_graph(
                {"block_id": candidate_block_id or f"note:p{page_index}:{idx}"},
                structure_graph,
                detail_tokens=[token_match.group(1)] if (token_match := _NOTE_TARGET_RE.search(note)) else [],
            )
            graph_confidence = decision.locality_confidence
            graph_reasons = decision.reasons
            if decision.scope_class == "detail_local":
                graph_scope_level = "subregion_local"
                graph_pseudo_page_id = decision.locality_ids.get("pseudo_page", "")
                graph_scope_targets = tuple(
                    target
                    for target in (
                        decision.locality_ids.get("pseudo_page", ""),
                        decision.locality_ids.get("subregion", ""),
                        decision.locality_ids.get("detail_region", ""),
                    )
                    if target
                )[:2]
                if graph_scope_targets:
                    graph_parent_region_id = next(
                        (
                            row.parent_region_id
                            for row in subregions
                            if row.subregion_id in set(graph_scope_targets)
                        ),
                        "",
                    )
            elif decision.scope_class == "column_local":
                graph_scope_level = "column_local"
                if decision.locality_ids.get("column_id"):
                    graph_scope_targets = (decision.locality_ids["column_id"],)
                    graph_parent_region_id = decision.locality_ids["column_id"]
            elif decision.scope_class == "page_global":
                graph_scope_level = "page_global"
                if decision.locality_ids.get("region_id"):
                    graph_parent_region_id = decision.locality_ids["region_id"]
        explicit_targets: list[str] = []
        token_match = _NOTE_TARGET_RE.search(note)
        if token_match:
            token = token_match.group(1).lower()
            for pseudo in pseudo_pages:
                if token and token in pseudo.text.lower():
                    explicit_targets.append(pseudo.pseudo_page_id)
        soft_targets: list[str] = []
        for pseudo in pseudo_pages:
            overlap = 0
            if pseudo.role in {"equipment_elevation", "riser_diagram_fragment"} and any(
                token in lowered for token in ("rack", "cabinet", "ground", "riser", "conduit", "tmgb", "tgb", "bond")
            ):
                overlap += 1
            if pseudo.role in {"mini_floorplan"} and any(token in lowered for token in ("room", "guestroom", "homerun", "route")):
                overlap += 1
            if pseudo.role in {"detail_note_block"} and any(token in lowered for token in ("detail", "mount", "terminate", "label")):
                overlap += 1
            if overlap > 0:
                soft_targets.append(pseudo.pseudo_page_id)
        targets = explicit_targets or soft_targets
        status = "scoped"
        scope_level = "page_global"
        general_note = _is_global_note_text(note) or is_strong_global_note(note)
        if not targets:
            if not general_note and page_observation is not None and page_observation.reading_order:
                for block in page_observation.layout_blocks:
                    body = block.text.lower()
                    if "detail" in body and any(token in body for token in ("riser", "rack", "guestroom", "equipment")):
                        guessed = next((pseudo.pseudo_page_id for pseudo in pseudo_pages if pseudo.role in {"equipment_elevation", "riser_diagram_fragment", "mini_floorplan"}), "")
                        if guessed:
                            targets = [guessed]
                            break
            if targets:
                scope_targets = (targets[0],)
                pseudo_page_id = targets[0]
                sub_id = next((pseudo.subregion_id for pseudo in pseudo_pages if pseudo.pseudo_page_id == targets[0]), "")
                parent_region_id = subregion_index.get(sub_id).parent_region_id if sub_id in subregion_index else ""
                scope_level = "subregion_local"
                confidence = 0.6
                status = "scoped"
            else:
                scope_targets = ()
                pseudo_page_id = ""
                parent_region_id = next((region.region_id for region in regions if region.kind == "notes_spec_block"), "")
                confidence = 0.8
        elif len(set(targets)) == 1:
            scope_targets = (targets[0],)
            pseudo_page_id = targets[0]
            sub_id = next((pseudo.subregion_id for pseudo in pseudo_pages if pseudo.pseudo_page_id == targets[0]), "")
            parent_region_id = subregion_index.get(sub_id).parent_region_id if sub_id in subregion_index else ""
            if general_note:
                scope_level = "page_global"
                confidence = 0.74
            else:
                scope_level = "subregion_local"
                confidence = 0.78
        else:
            scope_targets = tuple(sorted(set(targets)))
            pseudo_page_id = ""
            parent_region_id = ""
            if general_note:
                scope_level = "page_global"
                status = "scoped"
                confidence = 0.62
            else:
                scope_level = "subregion_local"
                status = "unresolved"
                confidence = 0.45
        if (
            scope_level == "page_global"
            and not general_note
            and column_regions
            and any(token in lowered for token in ("note", "spec", "require", "cable", "conduit", "termination", "label", "room", "detail"))
        ):
            scope_level = "column_local"
            scope_targets = tuple(region.region_id for region in column_regions[:2])
            parent_region_id = column_regions[0].region_id
            confidence = max(confidence, 0.62)
        if (
            scope_level == "page_global"
            and not general_note
            and holdout_column_lanes
            and page_observation is not None
            and False
        ):
            matched = next(
                (
                    block
                    for block in page_observation.layout_blocks
                    if block.text and any(tok in block.text.lower() for tok in lowered.split()[:4])
                ),
                None,
            )
            if matched is not None:
                decision = classify_note_scope_with_columns(
                    matched,
                    pseudo_pages=pseudo_pages,
                    column_lanes=holdout_column_lanes,
                    detail_tokens=[tok for tok in ("detail", "riser", "rack", "cabinet", "label", "termination") if tok in lowered],
                )
                if decision.get("scope_class") in {"detail_local", "column_local"}:
                    mapped_scope = "subregion_local" if decision.get("scope_class") == "detail_local" else "column_local"
                    scope_level = mapped_scope
                    confidence = max(confidence, float(decision.get("confidence", 0.0)))
                    if scope_level == "column_local":
                        col_id = decision.get("locality_ids", {}).get("column_id", "")
                        if col_id:
                            scope_targets = (col_id,)
                            parent_region_id = col_id
                    status = "scoped"
        if (
            scope_level == "page_global"
            and not general_note
            and any(token in lowered for token in ("detail", "typ", "riser", "rack", "elevation", "cabinet", "ground"))
            and pseudo_pages
        ):
            local_targets = list(strongest_local_pseudos or tuple(pseudo.pseudo_page_id for pseudo in pseudo_pages))
            if local_targets:
                scope_level = "subregion_local"
                scope_targets = tuple(local_targets[:2])
                pseudo_page_id = local_targets[0]
                status = "scoped"
                confidence = max(confidence, 0.68)
        if (
            scope_level == "page_global"
            and any(token in lowered for token in ("detail", "riser", "rack", "equipment", "guestroom", "support", "pathway", "elevation", "conduit"))
        ):
            if pseudo_pages:
                local_targets = tuple(pseudo.pseudo_page_id for pseudo in pseudo_pages if pseudo.pseudo_page_id)
                if local_targets:
                    scope_level = "subregion_local"
                    scope_targets = local_targets[:2]
                    pseudo_page_id = local_targets[0]
                    status = "scoped"
                    confidence = max(confidence, 0.66)
            elif column_regions:
                scope_level = "column_local"
                scope_targets = tuple(region.region_id for region in column_regions[:2])
                parent_region_id = column_regions[0].region_id
                status = "scoped"
                confidence = max(confidence, 0.62)
            elif regions:
                scope_level = "column_local"
                scope_targets = (regions[0].region_id,)
                parent_region_id = regions[0].region_id
                status = "scoped"
                confidence = max(confidence, 0.6)
        # Fail closed for ambiguous non-global notes: prefer explicit local scope over silent page-global collapse.
        if scope_level == "page_global" and not general_note:
            if strongest_local_pseudos:
                scope_level = "subregion_local"
                scope_targets = tuple(strongest_local_pseudos[:2])
                pseudo_page_id = strongest_local_pseudos[0]
                status = "scoped"
                confidence = max(confidence, 0.66)
            elif column_regions:
                scope_level = "column_local"
                scope_targets = tuple(region.region_id for region in column_regions[:2])
                parent_region_id = column_regions[0].region_id
                status = "scoped"
                confidence = max(confidence, 0.6)
        if general_note and graph_scope_level and graph_scope_level != "page_global":
            graph_scope_level = ""
        if graph_scope_level and graph_confidence >= max(0.62, confidence):
            scope_level = graph_scope_level
            if graph_scope_targets:
                scope_targets = graph_scope_targets
            if graph_parent_region_id:
                parent_region_id = graph_parent_region_id
            if graph_pseudo_page_id:
                pseudo_page_id = graph_pseudo_page_id
            status = "scoped" if graph_scope_level != "page_global" else status
            confidence = graph_confidence
        matched_pseudo = next((pseudo for pseudo in pseudo_pages if pseudo.pseudo_page_id == pseudo_page_id), None)
        matched_subregion = subregion_index.get(matched_pseudo.subregion_id, None) if matched_pseudo is not None else None
        scoped_note_dict = close_locality_scope_if_strong(
            {
                "scope_level": scope_level,
                "scope_confidence": confidence,
                "status": status,
                "metadata": {},
            },
            same_detail_region=bool(matched_subregion and matched_subregion.detail_region_id),
            same_subregion=bool(matched_pseudo and matched_pseudo.subregion_id),
            same_pseudo_page=bool(pseudo_page_id),
            same_column=bool(parent_region_id and "column" in str(parent_region_id).lower()),
            detail_cue_present=any(token in lowered for token in ("detail", "riser", "rack", "cabinet", "termination", "pathway", "support")),
        )
        scope_level = str(scoped_note_dict.get("scope_level", scope_level))
        confidence = float(scoped_note_dict.get("scope_confidence", confidence))
        status = str(scoped_note_dict.get("status", status))
        link = SiteSchematicScopedNoteLink(
            link_id=f"scoped_note:p{page_index}:{idx}",
            page_index=page_index,
            note_text=note,
            scope_level=scope_level,
            scope_targets=scope_targets,
            confidence=confidence,
            status=status,
            parent_region_id=parent_region_id,
            pseudo_page_id=pseudo_page_id,
            source_mode="scope_heuristic",
            metadata={
                "locality_confidence": round(confidence, 4),
                "structure_graph_reasons": tuple(graph_reasons),
            },
        )
        link, _ = ensure_locality_provenance(
            link,
            parent_region_id=parent_region_id,
            detail_region_id="",
            subregion_id="",
            pseudo_page_id=pseudo_page_id,
        )
        links.append(link)
    return tuple(links)


def classify_subregions(
    *,
    page_index: int,
    sheet_type: str,
    detail_regions: tuple[SiteSchematicDetailRegion, ...],
) -> tuple[SiteSchematicSubregion, ...]:
    rows: list[SiteSchematicSubregion] = []
    for idx, detail in enumerate(detail_regions, start=1):
        role = classify_subregion_role(
            text=detail.text,
            sheet_type=sheet_type,
            parent_kind=str(detail.metadata.get("parent_kind", "")),
        )
        rows.append(
            SiteSchematicSubregion(
                subregion_id=f"subregion:p{page_index}:{idx}",
                page_index=page_index,
                parent_region_id=detail.parent_region_id,
                detail_region_id=detail.detail_region_id,
                role=role,
                text=detail.text,
                confidence=detail.confidence,
                bbox=detail.bbox,
                source_mode=detail.source_mode,
                metadata={"sheet_type": sheet_type},
            )
        )
    return tuple(rows)


def _augment_phasec_regions(
    *,
    page_index: int,
    sheet_type: str,
    sheet_number: str,
    base_regions: tuple[SiteSchematicRegion, ...],
    page_observation: SiteSchematicPageObservation | None,
    universal_tables: tuple[SiteSchematicUniversalTable, ...],
) -> tuple[SiteSchematicRegion, ...]:
    out: list[SiteSchematicRegion] = list(base_regions)
    by_kind: set[str] = {row.kind for row in out}
    page_bbox = _fallback_bbox_from_regions(base_regions) or (0.0, 0.0, 1.0, 1.0)

    def add_region(kind: str, *, text: str, bbox: tuple[float, float, float, float] | None, confidence: float, source_mode: str, metadata: dict | None = None) -> None:
        region_kind = _phasec_kind_overrides_for_sheet(sheet_number=sheet_number, kind=kind, text=text)
        existing = next((row for row in out if row.kind == region_kind and (bbox is None or row.bbox == bbox)), None)
        if existing is not None:
            return
        out.append(
            SiteSchematicRegion(
                region_id=f"p{page_index}:phasec:{region_kind}:{len(out) + 1}",
                page_index=page_index,
                kind=region_kind,
                text=_clean(text),
                confidence=max(0.5, confidence),
                bbox=bbox or page_bbox,
                source_mode=source_mode,
                metadata=metadata or {},
            )
        )
        by_kind.add(region_kind)

    # Table-first region anchoring: reuse universal table spine as coarse-region primitives.
    for table in universal_tables:
        add_region(
            _table_kind_to_region_kind(
                table_kind=table.table_kind,
                sheet_number=sheet_number,
                table_text="\n".join(row.raw_text_joined for row in table.rows),
            ),
            text="\n".join(cell.raw_text for row in table.rows for cell in row.cells if cell.raw_text) or table.table_kind,
            bbox=table.bbox,
            confidence=max(0.6, table.confidence),
            source_mode="table_anchor_phasec",
            metadata={
                "phasec_anchor": "universal_table",
                "source_table_ids": [table.table_id],
                "table_kind": table.table_kind,
            },
        )

    header_rows = [
        row
        for row in (page_observation.layout_blocks if page_observation is not None else ())
        if row.text and row.confidence >= 0.65 and (_SECTION_HEADER_RE.match(_clean(row.text)) or row.role == "heading")
    ]
    for row in header_rows:
        hint_kind = _header_hint_kind(row.text)
        if hint_kind is not None:
            add_region(
                hint_kind,
                text=row.text,
                bbox=row.bbox,
                confidence=row.confidence,
                source_mode=row.source_mode or "model_assisted",
                metadata={"phasec_splitter": "header_hint"},
            )

    if page_observation is not None and (sheet_type == "notes_spec" or sheet_number == "T000"):
        note_blocks = [
            row
            for row in page_observation.layout_blocks
            if row.bbox is not None
            and row.text
            and (
                any(token in row.text.lower() for token in _NOTE_HEADER_HINTS)
                or row.role in {"text", "paragraph", "heading"}
                or len(row.text.split()) >= 8
            )
        ]
        if note_blocks:
            lanes = infer_holdout_columns(note_blocks, page_width=max(1.0, page_bbox[2] - page_bbox[0]))
            for lane in lanes:
                add_region(
                    "notes_spec_column",
                    text="notes/spec column",
                    bbox=lane.bbox,
                    confidence=max(0.74, lane.confidence),
                    source_mode="phasec_column_preservation",
                    metadata={
                        "phasec_multi_column": True,
                        "column_id": lane.column_id,
                        "member_ids": lane.member_ids,
                    },
                )
        elif sheet_type == "notes_spec":
            # Fail closed: prefer explicit dual-column placeholders over silent single-column collapse.
            split_x = round((page_bbox[0] + page_bbox[2]) / 2.0, 4)
            add_region(
                "notes_spec_column",
                text="notes/spec left column",
                bbox=(page_bbox[0], page_bbox[1], split_x, page_bbox[3]),
                confidence=0.62,
                source_mode="phasec_column_backfill",
                metadata={"phasec_multi_column": True, "column_index": 1},
            )
            add_region(
                "notes_spec_column",
                text="notes/spec right column",
                bbox=(split_x, page_bbox[1], page_bbox[2], page_bbox[3]),
                confidence=0.62,
                source_mode="phasec_column_backfill",
                metadata={"phasec_multi_column": True, "column_index": 2},
            )

    if sheet_number in {"T700", "T900", "T905", "T906", "TC502"}:
        detail_like = [
            row
            for row in (page_observation.layout_blocks if page_observation is not None else ())
            if row.bbox is not None and row.text and _DETAIL_HEADER_RE.search(row.text) and row.confidence >= 0.62
        ]
        for block in detail_like[:20]:
            add_region(
                "detail_frame",
                text=block.text,
                bbox=block.bbox,
                confidence=block.confidence,
                source_mode=block.source_mode or "model_assisted",
                metadata={"phasec_locality_cluster": True},
            )
            if "note" in block.text.lower():
                add_region(
                    "local_detail_note_block",
                    text=block.text,
                    bbox=block.bbox,
                    confidence=block.confidence,
                    source_mode=block.source_mode or "model_assisted",
                    metadata={"phasec_note_scope": "detail_local"},
                )

    if sheet_number == "TC001":
        for token, kind in (
            ("general notes", "general_notes_block"),
            ("horizontal cabling", "horizontal_cabling_notes_block"),
            ("junction box", "junction_box_conduit_notes_block"),
            ("conduit notes", "junction_box_conduit_notes_block"),
        ):
            if any(token in row.text.lower() for row in out if row.text):
                add_region(
                    kind,
                    text=token,
                    bbox=None,
                    confidence=0.7,
                    source_mode="phasec_header_split",
                    metadata={"phasec_splitter": "tokenized"},
                )

    required = _PHASEC_REQUIRED_REGION_KINDS.get(sheet_number, ())
    for kind in required:
        if kind not in by_kind:
            if kind == "notes_spec_column" and sheet_number == "T000":
                left_bbox = (page_bbox[0], page_bbox[1], round((page_bbox[0] + page_bbox[2]) / 2.0, 4), page_bbox[3])
                right_bbox = (left_bbox[2], page_bbox[1], page_bbox[2], page_bbox[3])
                add_region(
                    "notes_spec_column",
                    text="notes/spec left column",
                    bbox=left_bbox,
                    confidence=0.6,
                    source_mode="phasec_required_backfill",
                    metadata={"phasec_backfill": True, "column_index": 1},
                )
                add_region(
                    "notes_spec_column",
                    text="notes/spec right column",
                    bbox=right_bbox,
                    confidence=0.6,
                    source_mode="phasec_required_backfill",
                    metadata={"phasec_backfill": True, "column_index": 2},
                )
                continue
            add_region(
                kind,
                text=f"{kind} placeholder",
                bbox=page_bbox,
                confidence=0.52,
                source_mode="phasec_required_backfill",
                metadata={"phasec_backfill": True},
            )
    if "title_block" not in by_kind:
        add_region(
            "title_block",
            text=sheet_number or sheet_type or "title block",
            bbox=page_bbox,
            confidence=0.55,
            source_mode="phasec_title_backfill",
            metadata={"phasec_backfill": True},
        )

    deduped: list[SiteSchematicRegion] = []
    seen: set[tuple[str, str, tuple[float, float, float, float] | None]] = set()
    for region in out:
        key = (region.kind, _clean(region.text), region.bbox)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(region)
    finalized: list[SiteSchematicRegion] = []
    for region in deduped:
        children = []
        region_text = (region.text or "").lower()
        for candidate in deduped:
            if candidate is region:
                continue
            if candidate.bbox is None:
                continue
            candidate_text = (candidate.text or "").lower()
            if candidate.kind == "detail_frame" and "detail" in region_text:
                children.append(candidate)
            elif candidate.kind == "notes_spec_column" and "notes" in region_text:
                children.append(candidate)
            elif candidate.kind.endswith("_block") and candidate.kind != region.kind and any(token in candidate_text for token in region_text.split()[:3]):
                children.append(candidate)
        updated, _ = complete_region_bbox_from_children(region, children, table_anchors=universal_tables)
        if updated.bbox is None:
            updated = replace(
                updated,
                bbox=page_bbox,
                metadata={**dict(updated.metadata), "bbox_completed_from_page": True},
            )
        finalized.append(updated)
    return tuple(finalized)


def build_page_regions(
    *,
    page_index: int,
    text: str,
    sheet_type: str,
    sheet_number: str = "",
    sheet_title: str = "",
    page_observation: SiteSchematicPageObservation | None = None,
    universal_tables: tuple[SiteSchematicUniversalTable, ...] = (),
) -> tuple[SiteSchematicRegion, ...]:
    base = _merge_region_strategies(
        page_index=page_index,
        text=text,
        sheet_type=sheet_type,
        sheet_title=sheet_title,
        page_observation=page_observation,
    )
    return _augment_phasec_regions(
        page_index=page_index,
        sheet_type=sheet_type,
        sheet_number=sheet_number,
        base_regions=base,
        page_observation=page_observation,
        universal_tables=universal_tables,
    )


def _build_page_regions_text_heuristic(*, page_index: int, text: str, sheet_type: str, sheet_title: str = "") -> tuple[SiteSchematicRegion, ...]:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    total = max(len(lines), 1)
    regions: list[SiteSchematicRegion] = []

    title_start = max(0, total - min(36, max(12, total // 4)))
    title_text = _slice_lines(lines, title_start, total)
    if title_text:
        regions.append(
            _region(
                f"p{page_index}:title_block",
                page_index,
                "title_block",
                title_text,
                0.74,
                _line_bbox(title_start, total, total, x0=0.0, x1=1.0),
                metadata={"sheet_title_hint": sheet_title},
            )
        )

    revision_idxs = [idx for idx, line in enumerate(lines) if any(token in line.lower() for token in ("revision", "issue no", "issue", "plot", "print date", "date", "seal"))]
    if revision_idxs:
        start = max(0, min(revision_idxs) - 1)
        end = min(total, max(revision_idxs) + 2)
        regions.append(
            _region(
                f"p{page_index}:revision_block",
                page_index,
                "revision_block",
                _slice_lines(lines, start, end),
                0.68,
                _line_bbox(start, end, total, x0=0.74, x1=1.0),
            )
        )

    drawing_idxs = _matching_line_indices(lines, _DRAWING_ROW_RE)
    if drawing_idxs:
        start = min(drawing_idxs)
        end = min(total, max(drawing_idxs) + 2)
        regions.append(
            _region(
                f"p{page_index}:schedule_table_block",
                page_index,
                "schedule_table_block",
                _slice_lines(lines, start, end),
                0.8,
                _line_bbox(start, end, total, x0=0.58, x1=1.0),
            )
        )

    note_idxs = _matching_line_indices(lines, _NOTE_LINE_RE)
    if sheet_type in {"notes_spec", "schedule_sheet"} or note_idxs:
        start = min(note_idxs) if note_idxs else 0
        end = max(note_idxs) + 2 if note_idxs else min(total, max(10, total - 4))
        regions.append(
            _region(
                f"p{page_index}:notes_spec_block",
                page_index,
                "notes_spec_block",
                _slice_lines(lines, start, min(end, total)),
                0.78 if sheet_type == "notes_spec" else 0.65,
                _line_bbox(start, min(end, total), total, x0=0.0, x1=1.0),
            )
        )

    if sheet_type == "legend_symbol" or "legend" in (text or "").lower() or "symbol" in (text or "").lower():
        legend_lines = [idx for idx, line in enumerate(lines) if any(token in line.lower() for token in ("legend", "symbol", "outlet", "wireless node", "cctv", "camera", "intercom", "card reader", "abbreviation", "telecommunications symbols", "telecomm symbol"))]
        if legend_lines:
            start = max(0, min(legend_lines) - 1)
            end = min(total, max(legend_lines) + 6)
            regions.append(
                _region(
                    f"p{page_index}:legend_block",
                    page_index,
                    "legend_block",
                    _slice_lines(lines, start, end),
                    0.84,
                    _line_bbox(start, end, total, x0=0.0, x1=0.62),
                )
            )
        abbrev_idxs = _matching_line_indices(lines, _ABBREV_LINE_RE)
        if abbrev_idxs:
            start = max(0, min(abbrev_idxs) - 1)
            end = min(total, max(abbrev_idxs) + 3)
            regions.append(
                _region(
                    f"p{page_index}:abbreviation_block",
                    page_index,
                    "abbreviation_block",
                    _slice_lines(lines, start, end),
                    0.8,
                    _line_bbox(start, end, total, x0=0.0, x1=0.45),
                )
            )

    if sheet_type in {"floorplan_overall", "floorplan_detail"}:
        body_end = title_start if title_start > 0 else total
        regions.append(
            _region(
                f"p{page_index}:plan_body_block",
                page_index,
                "plan_body_block",
                _slice_lines(lines, 0, body_end),
                0.76,
                (0.0, 0.0, 1.0, 0.84),
            )
        )
    elif sheet_type in {"riser_diagram", "rack_detail", "installation_detail", "equipment_room_layout"}:
        regions.append(
            _region(
                f"p{page_index}:detail_block",
                page_index,
                "detail_block",
                _slice_lines(lines, 0, title_start if title_start > 0 else total),
                0.74,
                (0.0, 0.0, 1.0, 0.84),
            )
        )
    else:
        regions.append(
            _region(
                f"p{page_index}:plan_body_block",
                page_index,
                "plan_body_block",
                _slice_lines(lines, 0, title_start if title_start > 0 else total),
                0.6,
                (0.0, 0.0, 1.0, 0.84),
            )
        )

    if sheet_type == "unknown":
        regions.append(
            _region(
                f"p{page_index}:border_noise_block",
                page_index,
                "border_noise_block",
                title_text,
                0.4,
                (0.82, 0.82, 1.0, 1.0),
            )
        )

    deduped: list[SiteSchematicRegion] = []
    seen: set[tuple[str, str]] = set()
    for region in regions:
        key = (region.kind, region.text)
        if key in seen or not region.text:
            continue
        seen.add(key)
        deduped.append(region)
    return tuple(deduped)


def _build_page_regions_from_observation(
    *,
    page_index: int,
    page_observation: SiteSchematicPageObservation,
    sheet_type: str,
    sheet_title: str,
) -> tuple[SiteSchematicRegion, ...]:
    if not page_observation.layout_blocks:
        return ()
    kind_rows: dict[str, dict[str, object]] = {}
    candidates = sorted(page_observation.layout_blocks, key=lambda row: row.confidence, reverse=True)[:160]
    for block in candidates:
        text = _clean(block.text)
        if not text or block.confidence < 0.62:
            continue
        kind = "plan_body_block"
        lowered = text.lower()
        hint_kind = str((block.metadata or {}).get("layout_hint_kind", "")).strip().lower()
        if hint_kind in {"table_grid", "legend_grid"}:
            kind = "schedule_table_block" if _DRAWING_ROW_RE.search(text) else "legend_block"
        elif hint_kind == "title_block":
            kind = "title_block"
        elif hint_kind == "notes_column":
            kind = "notes_spec_block"
        elif (block.role == "table" and ("|" in text or "\t" in text or _DRAWING_ROW_RE.search(text))) or _DRAWING_ROW_RE.search(text):
            kind = "schedule_table_block"
        elif _text_has_any(lowered, ("legend", "symbol", "wireless", "camera", "outlet")):
            kind = "legend_block"
        elif _ABBREV_LINE_RE.search(text) or _text_has_any(lowered, ("abbreviation", "abbr")):
            kind = "abbreviation_block"
        elif _NOTE_LINE_RE.search(text) or _text_has_any(lowered, ("general notes", "keyed notes", "note")):
            kind = "notes_spec_block"
        elif _text_has_any(lowered, ("revision", "issue", "print date", "seal")):
            kind = "revision_block"
        elif _text_has_any(lowered, ("sheet no", "sheet title", "drawing title")) and len(text) <= 180:
            kind = "title_block"
        elif sheet_type in {"riser_diagram", "rack_detail", "installation_detail", "equipment_room_layout"}:
            kind = "detail_block"
        row = kind_rows.setdefault(
            kind,
            {
                "texts": [],
                "bbox": None,
                "confidence_sum": 0.0,
                "count": 0,
                "provider": block.provider,
                "source_mode": block.source_mode or "model_assisted",
            },
        )
        row["texts"].append(text)
        row["bbox"] = _union_bbox(row["bbox"], _bbox_or_none(block.bbox))
        row["confidence_sum"] = float(row["confidence_sum"]) + float(block.confidence)
        row["count"] = int(row["count"]) + 1
    out: list[SiteSchematicRegion] = []
    for kind, payload in kind_rows.items():
        count = max(1, int(payload["count"]))
        text = "\n".join(str(item) for item in payload["texts"])
        out.append(
            SiteSchematicRegion(
                region_id=f"p{page_index}:{kind}:obs",
                page_index=page_index,
                kind=kind,
                text=_clean(text),
                confidence=min(0.98, max(0.5, float(payload["confidence_sum"]) / count)),
                bbox=_bbox_or_none(payload["bbox"]),
                source_mode=str(payload["source_mode"]),
                metadata={
                    "sheet_title_hint": sheet_title,
                    "provider": str(payload["provider"] or page_observation.provider),
                    "from_observation": True,
                },
            )
        )
    return tuple(out)


def _merge_region_strategies(
    *,
    page_index: int,
    text: str,
    sheet_type: str,
    sheet_title: str,
    page_observation: SiteSchematicPageObservation | None,
) -> tuple[SiteSchematicRegion, ...]:
    heuristic_regions = _build_page_regions_text_heuristic(
        page_index=page_index,
        text=text,
        sheet_type=sheet_type,
        sheet_title=sheet_title,
    )
    if page_observation is None:
        return heuristic_regions
    observed_regions = _build_page_regions_from_observation(
        page_index=page_index,
        page_observation=page_observation,
        sheet_type=sheet_type,
        sheet_title=sheet_title,
    )
    if not observed_regions:
        return heuristic_regions
    merged: dict[str, SiteSchematicRegion] = {region.kind: region for region in heuristic_regions}
    for region in observed_regions:
        merged[region.kind] = region
    ordered = list(merged.values())
    ordered.sort(key=lambda row: row.region_id)
    return tuple(ordered)
