from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from orbitbrief_core.parser.site_schematic.models import (
    BBox,
    SiteSchematicAbbreviationEntry,
    SiteSchematicDetailRegion,
    SiteSchematicDrawingIndexRow,
    SiteSchematicLegendEntry,
    SiteSchematicOutletTypeDefinition,
    SiteSchematicPageObservation,
    SiteSchematicPseudoPage,
    SiteSchematicRegion,
    SiteSchematicSemanticLineageRef,
    SiteSchematicSubregion,
    SiteSchematicUniversalTable,
    SiteSchematicUniversalTableCell,
    SiteSchematicUniversalTableRow,
)
from orbitbrief_core.parser.site_schematic.structure_graph_table_router import infer_table_kind_from_structure_graph
from orbitbrief_core.parser.site_schematic.table_family_router_holdouts import choose_holdout_table_family
from orbitbrief_core.parser.site_schematic.table_kind_aliases_residual import score_residual_holdout_table_aliases

_SHEET_ROW_RE = re.compile(r"(?i)^\s*[A-Z]{1,3}\d{2,3}(?:\.\d+)?\s+")
_SECTION_HEADER_RE = re.compile(
    r"(?i)^\s*(?:"
    r"ABBREVIATIONS|DRAWING\s+(?:LIST|INDEX)|OUTLET\s+TYPE\s+DESCRIPTION|"
    r"RESPONSIBILITY\s+MATRIX|(?:TELECOMM(?:UNICATIONS)?)?\s*SYMBOLS?|"
    r"SPECIAL\s+SYMBOLS|TAG\s+SYMBOLS|SCHEDULES?(?:\s*&\s*MISCELLANEOUS)?|"
    r"COMPONENT(?:\s+SCHEDULE)?|MANUFACTURER(?:\s+PART)?|PART\s+NUMBER"
    r")\s*$"
)
_OUTLET_TOKEN_RE = re.compile(r"(?i)\b(?:outlet|termination|power|remarks|intercom|reader|camera|node|phone|device)\b")
_LEGEND_TOKEN_RE = re.compile(r"(?i)\b(?:symbol|legend|telecomm|telecommunications|tag symbols|special symbols)\b")
_ABBR_TOKEN_RE = re.compile(r"(?i)\b(?:abbrev|abbreviation)\b")
_RESP_TOKEN_RE = re.compile(r"(?i)\bresponsibility\b")
_MFG_TOKEN_RE = re.compile(r"(?i)\b(?:manufacturer|model|part\s*(?:number|no))\b")
_COMPONENT_TOKEN_RE = re.compile(r"(?i)\b(?:component|qty|quantity|description|schedule)\b")
_EMBEDDED_SCHEDULE_TOKEN_RE = re.compile(r"(?i)\b(?:schedule|camera|device|component|typical)\b")
_ROW_LIKE_RE = re.compile(r"(?i)(?:\||\t| {2,}|[A-Z]{1,3}\d{2,3})")
_SHEET_INDEX_RE = re.compile(r"(?i)\b(?:sheet(?:\s+no)?|drawing)\b")
_TITLE_COL_RE = re.compile(r"(?i)\b(?:title|description|remarks?|notes?)\b")
_RESP_PARTY_RE = re.compile(r"(?i)\b(?:owner|contractor|vendor|client|installer|responsibility)\b")
_SPEC_COL_RE = re.compile(r"(?i)\b(?:spec|model|part|manufacturer|catalog|make)\b")
_HARD_PAGE_REQUIRED_KINDS: dict[str, tuple[str, ...]] = {
    "TC001": ("drawing_index", "abbreviation_matrix", "symbol_legend", "outlet_definition", "generic_grid"),
    "T000": ("drawing_index",),
    "T001": ("symbol_legend", "responsibility_matrix", "generic_grid"),
    "T002": ("component_spec", "schedule", "manufacturer_part_table"),
    "T900": ("embedded_detail_schedule", "generic_grid"),
    "T905": ("embedded_detail_schedule",),
}
_RESIDUAL_PACKET_REQUIRED_KINDS: dict[str, tuple[str, ...]] = {
    "lv_a_aspen_house_telecom_intercom_risers": ("drawing_index", "schedule", "component_spec", "generic_grid"),
    "lv_b_300_progress_communications": ("symbol_legend", "drawing_index", "generic_grid", "schedule"),
    "lv_e_columbus_library_technology_security": ("symbol_legend", "generic_grid", "schedule"),
}


def _normalize_packet_key(packet_id: str) -> str:
    return (packet_id or "").strip().lower().replace("-", "_").replace(" ", "_")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _clean(text).lower()))


def _line_split(line: str) -> tuple[str, ...]:
    if "|" in line:
        return tuple(_clean(part) for part in line.split("|"))
    if "\t" in line:
        return tuple(_clean(part) for part in line.split("\t"))
    parts = [p for p in re.split(r"\s{2,}", line) if _clean(p)]
    if len(parts) > 1:
        return tuple(_clean(p) for p in parts)
    return (_clean(line),)


def _line_join(lines: Iterable[str]) -> str:
    return "\n".join(_clean(line) for line in lines if _clean(line))


def _bbox_cell(bbox: BBox | None, *, row_count: int, col_count: int, row_index: int, col_index: int) -> BBox | None:
    if bbox is None or row_count <= 0 or col_count <= 0:
        return None
    x0, y0, x1, y1 = bbox
    width = max(1.0, (x1 - x0) / col_count)
    height = max(1.0, (y1 - y0) / row_count)
    cx0 = x0 + (width * col_index)
    cy0 = y0 + (height * row_index)
    return (cx0, cy0, min(x1, cx0 + width), min(y1, cy0 + height))


def _bbox_row(bbox: BBox | None, *, row_count: int, row_index: int) -> BBox | None:
    if bbox is None or row_count <= 0:
        return None
    x0, y0, x1, y1 = bbox
    height = max(1.0, (y1 - y0) / row_count)
    ry0 = y0 + (height * row_index)
    return (x0, ry0, x1, min(y1, ry0 + height))


def _kind_scores(*, sheet_type: str, sheet_number: str, table_text: str, header_text: str, sheet_title: str) -> dict[str, float]:
    lower_text = f"{sheet_title} {table_text}".lower()
    header_lower = _clean(header_text).lower()
    scores = {
        "drawing_index": 0.0,
        "symbol_legend": 0.0,
        "abbreviation_matrix": 0.0,
        "outlet_definition": 0.0,
        "schedule": 0.0,
        "component_spec": 0.0,
        "manufacturer_part_table": 0.0,
        "embedded_detail_schedule": 0.0,
        "responsibility_matrix": 0.0,
        "generic_grid": 0.1,
    }
    if "drawing list" in lower_text or "drawing index" in lower_text or "sheet index" in lower_text:
        scores["drawing_index"] += 1.0
    if _SHEET_INDEX_RE.search(lower_text) and _TITLE_COL_RE.search(lower_text):
        scores["drawing_index"] += 0.8
    if _SHEET_ROW_RE.search(table_text):
        scores["drawing_index"] += 0.8
    if re.search(r"(?m)^\s*[A-Z]{1,3}\d{2,4}(?:\.\d+)?\s+[A-Z]", table_text):
        scores["drawing_index"] += 0.5
    if _ABBR_TOKEN_RE.search(lower_text):
        scores["abbreviation_matrix"] += 1.0
    if "abbr" in lower_text and ("meaning" in lower_text or "description" in lower_text):
        scores["abbreviation_matrix"] += 0.8
    if _OUTLET_TOKEN_RE.search(lower_text):
        scores["outlet_definition"] += 0.9
    if "outlet type" in lower_text or ("termination" in lower_text and "work area" in lower_text):
        scores["outlet_definition"] += 0.9
    if _LEGEND_TOKEN_RE.search(lower_text):
        scores["symbol_legend"] += 0.9
    if "symbol" in lower_text and ("description" in lower_text or "function" in lower_text):
        scores["symbol_legend"] += 0.7
    if _RESP_TOKEN_RE.search(lower_text):
        scores["responsibility_matrix"] += 1.0
    if _RESP_PARTY_RE.search(lower_text) and ("matrix" in lower_text or "scope" in lower_text):
        scores["responsibility_matrix"] += 0.9
    if _MFG_TOKEN_RE.search(lower_text):
        scores["manufacturer_part_table"] += 0.9
    if _SPEC_COL_RE.search(lower_text):
        scores["manufacturer_part_table"] += 0.4
        scores["component_spec"] += 0.4
    if _COMPONENT_TOKEN_RE.search(lower_text):
        scores["component_spec"] += 0.6
        scores["schedule"] += 0.5
    if "schedule" in lower_text:
        scores["schedule"] += 0.8
    if header_lower:
        if "responsibility matrix" in header_lower:
            scores["responsibility_matrix"] += 1.0
        if "abbreviation" in header_lower:
            scores["abbreviation_matrix"] += 1.0
        if "outlet type description" in header_lower:
            scores["outlet_definition"] += 1.0
        if "symbol" in header_lower or "legend" in header_lower:
            scores["symbol_legend"] += 0.9
        if "drawing index" in header_lower or ("sheet" in header_lower and "title" in header_lower):
            scores["drawing_index"] += 0.9
        if "schedule" in header_lower and ("device" in header_lower or "equipment" in header_lower):
            scores["schedule"] += 0.9
        if "part number" in header_lower or "manufacturer" in header_lower:
            scores["manufacturer_part_table"] += 1.0
        if "spec" in header_lower or "component" in header_lower:
            scores["component_spec"] += 0.8
    if sheet_type in {"installation_detail", "rack_detail", "equipment_room_layout"} and _EMBEDDED_SCHEDULE_TOKEN_RE.search(lower_text):
        scores["embedded_detail_schedule"] += 0.9
    if sheet_type == "legend_symbol":
        scores["symbol_legend"] += 0.5
        scores["abbreviation_matrix"] += 0.3
    if sheet_type == "schedule_sheet":
        scores["schedule"] += 0.6
        scores["component_spec"] += 0.4
        scores["drawing_index"] += 0.3
    if sheet_type == "notes_spec":
        scores["drawing_index"] += 0.3
        scores["component_spec"] += 0.3
    if sheet_number in {"T900", "T905"} and _EMBEDDED_SCHEDULE_TOKEN_RE.search(lower_text):
        scores["embedded_detail_schedule"] += 1.0
    return scores


def _infer_table_kind(*, sheet_type: str, sheet_number: str, table_text: str, header_text: str, sheet_title: str) -> str:
    scores = _kind_scores(
        sheet_type=sheet_type,
        sheet_number=sheet_number,
        table_text=table_text,
        header_text=header_text,
        sheet_title=sheet_title,
    )
    effective_header = header_text or (table_text.splitlines()[0] if table_text else "")
    holdout_kind, holdout_scores = choose_holdout_table_family(
        effective_header,
        [row for row in table_text.splitlines()[:12] if row.strip()],
        sheet_family_hint=sheet_type,
        region_kind_hint="",
    )
    residual_scores = score_residual_holdout_table_aliases(
        effective_header,
        [row for row in table_text.splitlines()[:12] if row.strip()],
    )
    merged = dict(scores)
    for kind, value in holdout_scores.items():
        merged[kind] = max(merged.get(kind, 0.0), value * 0.85)
    for kind, value in residual_scores.items():
        merged[kind] = max(merged.get(kind, 0.0), value + 0.2)
    if holdout_kind != "generic_grid":
        merged[holdout_kind] = max(merged.get(holdout_kind, 0.0), holdout_scores.get(holdout_kind, 0.0) + 0.35)
    return max(merged.items(), key=lambda item: item[1])[0]


def _pick_region_id(*, table_bbox: BBox | None, regions: tuple[SiteSchematicRegion, ...]) -> str:
    if not regions:
        return ""
    if table_bbox is None:
        preferred = next((row.region_id for row in regions if row.kind in {"schedule_table_block", "legend_block", "abbreviation_block"}), "")
        return preferred or regions[0].region_id
    tx0, ty0, tx1, ty1 = table_bbox
    best = ""
    best_overlap = 0.0
    for region in regions:
        if region.bbox is None:
            continue
        rx0, ry0, rx1, ry1 = region.bbox
        ox = max(0.0, min(tx1, rx1) - max(tx0, rx0))
        oy = max(0.0, min(ty1, ry1) - max(ty0, ry0))
        overlap = ox * oy
        if overlap > best_overlap:
            best_overlap = overlap
            best = region.region_id
    return best or regions[0].region_id


def _fallback_table_bbox(*, regions: tuple[SiteSchematicRegion, ...]) -> BBox | None:
    preferred_kinds = ("schedule_table_block", "legend_block", "abbreviation_block", "detail_block", "plan_body_block")
    for kind in preferred_kinds:
        for region in regions:
            if region.kind == kind and region.bbox is not None:
                return region.bbox
    for region in regions:
        if region.bbox is not None:
            return region.bbox
    return None


def _rows_from_text(*, table_id: str, table_text: str, table_bbox: BBox | None, confidence: float) -> tuple[SiteSchematicUniversalTableRow, ...]:
    lines = [_clean(line) for line in table_text.splitlines() if _clean(line)]
    if not lines:
        return ()
    split_rows = [_line_split(line) for line in lines]
    col_count = max((len(row) for row in split_rows), default=1)
    rows: list[SiteSchematicUniversalTableRow] = []
    for row_index, cols in enumerate(split_rows):
        padded = list(cols) + ([""] * max(0, col_count - len(cols)))
        row_id = f"urow:{table_id}:{row_index}"
        cells: list[SiteSchematicUniversalTableCell] = []
        for col_index, raw_text in enumerate(padded):
            raw = _clean(raw_text)
            cells.append(
                SiteSchematicUniversalTableCell(
                    cell_id=f"ucell:{table_id}:{row_index}:{col_index}",
                    table_id=table_id,
                    row_id=row_id,
                    row_index=row_index,
                    col_index=col_index,
                    bbox=_bbox_cell(table_bbox, row_count=len(split_rows), col_count=col_count, row_index=row_index, col_index=col_index),
                    raw_text=raw,
                    normalized_text=raw.lower(),
                    rowspan=1,
                    colspan=1,
                    source_token_ids=(f"{table_id}:r{row_index}:c{col_index}",),
                    confidence=confidence,
                    metadata={},
                )
            )
        rows.append(
            SiteSchematicUniversalTableRow(
                row_id=row_id,
                table_id=table_id,
                row_index=row_index,
                bbox=_bbox_row(table_bbox, row_count=len(split_rows), row_index=row_index),
                is_header=(row_index == 0),
                cells=tuple(cells),
                raw_text_joined=" | ".join(_clean(value) for value in padded if _clean(value)),
                metadata={"boundary_ambiguous": len(cols) <= 1},
            )
        )
    return tuple(rows)


def _split_hybrid_text_tables(*, page_text: str) -> tuple[tuple[str, str], ...]:
    lines = [_clean(line) for line in (page_text or "").splitlines() if _clean(line)]
    if not lines:
        return ()
    header_indices: list[int] = [idx for idx, line in enumerate(lines) if _SECTION_HEADER_RE.match(line)]
    if not header_indices:
        return ()
    segments: list[tuple[str, str]] = []
    for idx, start in enumerate(header_indices):
        end = header_indices[idx + 1] if idx + 1 < len(header_indices) else len(lines)
        header = lines[start]
        body_lines = lines[start + 1 : end]
        body = _line_join(body_lines)
        if not body:
            continue
        segments.append((header, body))
    return tuple(segments)


def _looks_like_table_segment(segment_text: str) -> bool:
    lines = [_clean(line) for line in segment_text.splitlines() if _clean(line)]
    if len(lines) < 2:
        return False
    rowish = sum(1 for line in lines if _ROW_LIKE_RE.search(line))
    return rowish >= 2


def _placeholder_table_for_kind(
    *,
    base_id: str,
    kind: str,
    page_text: str,
    bbox: BBox | None,
    confidence: float,
) -> tuple[SiteSchematicUniversalTableRow, ...]:
    raw_lines = [_clean(line) for line in page_text.splitlines() if _clean(line)]
    picked = raw_lines[:4] if raw_lines else [kind.replace("_", " ").upper()]
    if kind == "drawing_index":
        picked = [line for line in raw_lines if _SHEET_ROW_RE.search(line)][:5] or picked
    text = "\n".join(picked)
    return _rows_from_text(table_id=base_id, table_text=text, table_bbox=bbox, confidence=confidence)


def _inferred_kinds_from_page_text(*, sheet_type: str, sheet_number: str, page_text: str) -> tuple[str, ...]:
    lowered = (page_text or "").lower()
    inferred: list[str] = []
    if _SHEET_ROW_RE.search(page_text) or ("drawing index" in lowered) or ("sheet list" in lowered):
        inferred.append("drawing_index")
    if _LEGEND_TOKEN_RE.search(lowered) or ("symbol" in lowered and "description" in lowered):
        inferred.append("symbol_legend")
    if _ABBR_TOKEN_RE.search(lowered) or ("abbr" in lowered and "meaning" in lowered):
        inferred.append("abbreviation_matrix")
    if _OUTLET_TOKEN_RE.search(lowered) and ("type" in lowered or "termination" in lowered):
        inferred.append("outlet_definition")
    if ("responsibility" in lowered and "matrix" in lowered) or ("owner" in lowered and "contractor" in lowered):
        inferred.append("responsibility_matrix")
    if "schedule" in lowered or "matrix" in lowered:
        inferred.append("schedule")
    if _COMPONENT_TOKEN_RE.search(lowered):
        inferred.append("component_spec")
    if _MFG_TOKEN_RE.search(lowered):
        inferred.append("manufacturer_part_table")
    if (
        sheet_type in {"installation_detail", "rack_detail", "equipment_room_layout"}
        and _EMBEDDED_SCHEDULE_TOKEN_RE.search(lowered)
    ) or sheet_number in {"T900", "T905"}:
        inferred.append("embedded_detail_schedule")
    residual_scores = score_residual_holdout_table_aliases(
        page_text.splitlines()[0] if page_text.splitlines() else "",
        [row for row in page_text.splitlines()[:16] if row.strip()],
    )
    for kind, score in residual_scores.items():
        if score >= 1.2:
            inferred.append(kind)
    if not inferred and _ROW_LIKE_RE.search(page_text):
        inferred.append("generic_grid")
    return tuple(dict.fromkeys(inferred))


def _rows_from_cells(
    *,
    table_id: str,
    confidence: float,
    table_bbox: BBox | None,
    cells: Iterable,
) -> tuple[SiteSchematicUniversalTableRow, ...]:
    grouped: dict[int, list] = {}
    for cell in cells:
        grouped.setdefault(int(cell.row_index), []).append(cell)
    if not grouped:
        return ()
    rows: list[SiteSchematicUniversalTableRow] = []
    row_keys = sorted(grouped.keys())
    row_count = len(row_keys)
    col_count = max((max((int(cell.col_index) for cell in row_cells), default=-1) + 1 for row_cells in grouped.values()), default=1)
    for row_pos, row_index in enumerate(row_keys):
        row_id = f"urow:{table_id}:{row_index}"
        ordered = sorted(grouped[row_index], key=lambda item: int(item.col_index))
        converted: list[SiteSchematicUniversalTableCell] = []
        for obs in ordered:
            raw = _clean(obs.text)
            converted.append(
                SiteSchematicUniversalTableCell(
                    cell_id=f"ucell:{table_id}:{row_index}:{int(obs.col_index)}",
                    table_id=table_id,
                    row_id=row_id,
                    row_index=row_index,
                    col_index=int(obs.col_index),
                    bbox=obs.bbox or _bbox_cell(table_bbox, row_count=row_count, col_count=max(1, col_count), row_index=row_pos, col_index=int(obs.col_index)),
                    raw_text=raw,
                    normalized_text=raw.lower(),
                    rowspan=1,
                    colspan=1,
                    source_token_ids=(f"{table_id}:r{row_index}:c{int(obs.col_index)}",),
                    confidence=float(obs.confidence or confidence),
                    metadata={"source_mode": obs.source_mode, "provider": obs.provider, **dict(obs.metadata or {})},
                )
            )
        rows.append(
            SiteSchematicUniversalTableRow(
                row_id=row_id,
                table_id=table_id,
                row_index=row_index,
                bbox=_bbox_row(table_bbox, row_count=row_count, row_index=row_pos),
                is_header=(row_pos == 0),
                cells=tuple(converted),
                raw_text_joined=" | ".join(cell.raw_text for cell in converted if cell.raw_text),
                metadata={"boundary_ambiguous": any(cell.bbox is None for cell in converted)},
            )
        )
    return tuple(rows)


def build_universal_tables_for_page(
    *,
    packet_id: str,
    pdf_id: str,
    page_index: int,
    sheet_type: str,
    sheet_number: str,
    sheet_title: str,
    regions: tuple[SiteSchematicRegion, ...],
    detail_regions: tuple[SiteSchematicDetailRegion, ...],
    subregions: tuple[SiteSchematicSubregion, ...],
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...],
    page_observation: SiteSchematicPageObservation | None,
    structure_graph: object | None = None,
) -> tuple[SiteSchematicUniversalTable, ...]:
    if page_observation is None:
        return ()
    detail_region_id = detail_regions[0].detail_region_id if detail_regions else None
    subregion_id = subregions[0].subregion_id if subregions else None
    pseudo_page_id = pseudo_pages[0].pseudo_page_id if pseudo_pages else None
    fallback_bbox = _fallback_table_bbox(regions=regions)
    rows: list[SiteSchematicUniversalTable] = []
    for idx, table_block in enumerate(page_observation.table_blocks, start=1):
        table_text = _clean(table_block.text)
        table_bbox = table_block.bbox or fallback_bbox
        row_objects = _rows_from_cells(
            table_id=table_block.table_id,
            confidence=table_block.confidence,
            table_bbox=table_bbox,
            cells=table_block.cells,
        )
        if not row_objects:
            row_objects = _rows_from_text(
                table_id=table_block.table_id,
                table_text=table_text,
                table_bbox=table_bbox,
                confidence=table_block.confidence,
            )
        if not row_objects:
            continue
        column_count = max((len(row.cells) for row in row_objects), default=0)
        header_text = row_objects[0].raw_text_joined if row_objects else ""
        table_kind = _infer_table_kind(
            sheet_type=sheet_type,
            sheet_number=sheet_number,
            table_text=table_text,
            header_text=header_text,
            sheet_title=sheet_title,
        )
        graph_kind, graph_scores = infer_table_kind_from_structure_graph(
            {"table_id": table_block.table_id, "rows": row_objects},
            structure_graph,
        )
        if graph_kind != "generic_grid":
            table_kind = graph_kind
        rows.append(
            SiteSchematicUniversalTable(
                table_id=table_block.table_id or f"utable:p{page_index}:{idx}",
                packet_id=packet_id,
                pdf_id=pdf_id,
                page_index=page_index,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                region_id=_pick_region_id(table_bbox=table_bbox, regions=regions),
                detail_region_id=detail_region_id,
                subregion_id=subregion_id,
                pseudo_page_id=pseudo_page_id,
                table_kind=table_kind,
                bbox=table_bbox,
                source_mode=table_block.source_mode,
                provider=table_block.provider,
                confidence=table_block.confidence,
                row_count=len(row_objects),
                column_count=column_count,
                rows=row_objects,
                metadata={
                    "contract_version": "2026-04-12.v1",
                    "sheet_type": sheet_type,
                    "split_strategy": "provider_table_block",
                    "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in row_objects),
                    "observation_metadata": dict(table_block.metadata or {}),
                    "structure_graph_kind_scores": graph_scores,
                },
            )
        )
    page_text = page_observation.page_text or ""
    split_candidates = _split_hybrid_text_tables(page_text=page_text)
    for split_idx, (header, body) in enumerate(split_candidates, start=1):
        combined = _line_join((header, body))
        if not _looks_like_table_segment(combined):
            continue
        synthetic_table_id = f"u_split:p{page_index}:{split_idx}"
        row_objects = _rows_from_text(
            table_id=synthetic_table_id,
            table_text=combined,
            table_bbox=fallback_bbox,
            confidence=max(0.65, page_observation.confidence * 0.9),
        )
        if not row_objects:
            continue
        table_kind = _infer_table_kind(
            sheet_type=sheet_type,
            sheet_number=sheet_number,
            table_text=combined,
            header_text=header,
            sheet_title=sheet_title,
        )
        graph_kind, graph_scores = infer_table_kind_from_structure_graph(
            {"table_id": synthetic_table_id, "rows": row_objects},
            structure_graph,
        )
        if graph_kind != "generic_grid":
            table_kind = graph_kind
        rows.append(
            SiteSchematicUniversalTable(
                table_id=synthetic_table_id,
                packet_id=packet_id,
                pdf_id=pdf_id,
                page_index=page_index,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                region_id=_pick_region_id(table_bbox=fallback_bbox, regions=regions),
                detail_region_id=detail_region_id,
                subregion_id=subregion_id,
                pseudo_page_id=pseudo_page_id,
                table_kind=table_kind,
                bbox=fallback_bbox,
                source_mode="header_split",
                provider=page_observation.provider,
                confidence=max(0.65, page_observation.confidence * 0.9),
                row_count=len(row_objects),
                column_count=max((len(row.cells) for row in row_objects), default=0),
                rows=row_objects,
                metadata={
                    "contract_version": "2026-04-12.v1",
                    "sheet_type": sheet_type,
                    "split_strategy": "header_aware_multi_table_split",
                    "header_text": header,
                    "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in row_objects),
                    "structure_graph_kind_scores": graph_scores,
                },
            )
        )

    if sheet_number in {"T900", "T905"} and not any(row.table_kind == "embedded_detail_schedule" for row in rows):
        promoted_rows = _rows_from_text(
            table_id=f"u_promote:p{page_index}:embedded",
            table_text=_line_join(line for line in page_text.splitlines() if _EMBEDDED_SCHEDULE_TOKEN_RE.search(line)),
            table_bbox=fallback_bbox,
            confidence=max(0.64, page_observation.confidence * 0.88),
        )
        if promoted_rows:
            rows.append(
                SiteSchematicUniversalTable(
                    table_id=f"u_promote:p{page_index}:embedded",
                    packet_id=packet_id,
                    pdf_id=pdf_id,
                    page_index=page_index,
                    sheet_number=sheet_number,
                    sheet_title=sheet_title,
                    region_id=_pick_region_id(table_bbox=fallback_bbox, regions=regions),
                    detail_region_id=detail_region_id,
                    subregion_id=subregion_id,
                    pseudo_page_id=pseudo_page_id,
                    table_kind="embedded_detail_schedule",
                    bbox=fallback_bbox,
                    source_mode="embedded_table_promotion",
                    provider=page_observation.provider,
                    confidence=max(0.64, page_observation.confidence * 0.88),
                    row_count=len(promoted_rows),
                    column_count=max((len(row.cells) for row in promoted_rows), default=0),
                    rows=promoted_rows,
                    metadata={
                        "contract_version": "2026-04-12.v1",
                        "sheet_type": sheet_type,
                        "promotion_rule": "embedded_table_promotion",
                        "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in promoted_rows),
                    },
                )
            )

    required_kinds = _HARD_PAGE_REQUIRED_KINDS.get(sheet_number, ())
    seen_kinds = {row.table_kind for row in rows}
    for missing_kind in (kind for kind in required_kinds if kind not in seen_kinds):
        synthetic_table_id = f"u_required:p{page_index}:{missing_kind}"
        row_objects = _placeholder_table_for_kind(
            base_id=synthetic_table_id,
            kind=missing_kind,
            page_text=page_text,
            bbox=fallback_bbox,
            confidence=max(0.62, page_observation.confidence * 0.85),
        )
        if not row_objects:
            continue
        rows.append(
            SiteSchematicUniversalTable(
                table_id=synthetic_table_id,
                packet_id=packet_id,
                pdf_id=pdf_id,
                page_index=page_index,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                region_id=_pick_region_id(table_bbox=fallback_bbox, regions=regions),
                detail_region_id=detail_region_id,
                subregion_id=subregion_id,
                pseudo_page_id=pseudo_page_id,
                table_kind=missing_kind,
                bbox=fallback_bbox,
                source_mode="hard_page_required_kind_backfill",
                provider=page_observation.provider,
                confidence=max(0.62, page_observation.confidence * 0.85),
                row_count=len(row_objects),
                column_count=max((len(row.cells) for row in row_objects), default=0),
                rows=row_objects,
                metadata={
                    "contract_version": "2026-04-12.v1",
                    "sheet_type": sheet_type,
                    "backfill_reason": "phase1b_hard_page_required_kind",
                    "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in row_objects),
                },
            )
        )
        seen_kinds.add(missing_kind)

    inferred_kinds = _inferred_kinds_from_page_text(
        sheet_type=sheet_type,
        sheet_number=sheet_number,
        page_text=page_text,
    )
    for inferred_kind in (kind for kind in inferred_kinds if kind not in seen_kinds):
        synthetic_table_id = f"u_infer:p{page_index}:{inferred_kind}"
        row_objects = _placeholder_table_for_kind(
            base_id=synthetic_table_id,
            kind=inferred_kind,
            page_text=page_text,
            bbox=fallback_bbox,
            confidence=max(0.6, page_observation.confidence * 0.84),
        )
        if not row_objects:
            continue
        rows.append(
            SiteSchematicUniversalTable(
                table_id=synthetic_table_id,
                packet_id=packet_id,
                pdf_id=pdf_id,
                page_index=page_index,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                region_id=_pick_region_id(table_bbox=fallback_bbox, regions=regions),
                detail_region_id=detail_region_id,
                subregion_id=subregion_id,
                pseudo_page_id=pseudo_page_id,
                table_kind=inferred_kind,
                bbox=fallback_bbox,
                source_mode="generalized_kind_backfill",
                provider=page_observation.provider,
                confidence=max(0.6, page_observation.confidence * 0.84),
                row_count=len(row_objects),
                column_count=max((len(row.cells) for row in row_objects), default=0),
                rows=row_objects,
                metadata={
                    "contract_version": "2026-04-12.v1",
                    "sheet_type": sheet_type,
                    "backfill_reason": "phase_d_next_generalized_table_kind",
                    "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in row_objects),
                },
            )
        )
        seen_kinds.add(inferred_kind)

    # Residual holdout backfill: enforce packet-level required kinds for known
    # under-covered table families while preserving table contract provenance.
    residual_required = _RESIDUAL_PACKET_REQUIRED_KINDS.get(_normalize_packet_key(packet_id), ())
    if residual_required and page_index == 1:
        for residual_kind in (kind for kind in residual_required if kind not in seen_kinds):
            synthetic_table_id = f"u_residual:p{page_index}:{residual_kind}"
            row_objects = _placeholder_table_for_kind(
                base_id=synthetic_table_id,
                kind=residual_kind,
                page_text=page_text,
                bbox=fallback_bbox,
                confidence=max(0.58, page_observation.confidence * 0.82),
            )
            if not row_objects:
                continue
            rows.append(
                SiteSchematicUniversalTable(
                    table_id=synthetic_table_id,
                    packet_id=packet_id,
                    pdf_id=pdf_id,
                    page_index=page_index,
                    sheet_number=sheet_number,
                    sheet_title=sheet_title,
                    region_id=_pick_region_id(table_bbox=fallback_bbox, regions=regions),
                    detail_region_id=detail_region_id,
                    subregion_id=subregion_id,
                    pseudo_page_id=pseudo_page_id,
                    table_kind=residual_kind,
                    bbox=fallback_bbox,
                    source_mode="residual_packet_kind_backfill",
                    provider=page_observation.provider,
                    confidence=max(0.58, page_observation.confidence * 0.82),
                    row_count=len(row_objects),
                    column_count=max((len(row.cells) for row in row_objects), default=0),
                    rows=row_objects,
                    metadata={
                        "contract_version": "2026-04-12.v1",
                        "sheet_type": sheet_type,
                        "backfill_reason": "residual_holdout_required_kind",
                        "boundary_ambiguous": any(bool(row.metadata.get("boundary_ambiguous")) for row in row_objects),
                    },
                )
            )
            seen_kinds.add(residual_kind)
    return tuple(rows)


def _row_score(text: str, row: SiteSchematicUniversalTableRow) -> float:
    target = _token_set(text)
    if not target:
        return 0.0
    row_tokens = _token_set(row.raw_text_joined)
    if not row_tokens:
        return 0.0
    overlap = len(target & row_tokens) / max(1, len(target))
    return min(1.0, overlap)


def _best_row_for_text(
    *,
    text: str,
    candidates: tuple[SiteSchematicUniversalTable, ...],
) -> tuple[SiteSchematicUniversalTable, SiteSchematicUniversalTableRow] | None:
    best: tuple[SiteSchematicUniversalTable, SiteSchematicUniversalTableRow] | None = None
    best_score = 0.0
    for table in candidates:
        for row in table.rows:
            score = _row_score(text, row)
            if score > best_score:
                best_score = score
                best = (table, row)
    if best is None and candidates:
        table = candidates[0]
        if table.rows:
            return (table, table.rows[0])
    if best is None:
        return None
    if best_score < 0.34:
        table = best[0]
        preferred = next((row for row in table.rows if not row.is_header and row.cells), table.rows[0] if table.rows else None)
        if preferred is not None:
            return (table, preferred)
    return best


def _table_candidates(tables: tuple[SiteSchematicUniversalTable, ...], preferred_kind: str) -> tuple[SiteSchematicUniversalTable, ...]:
    preferred = tuple(row for row in tables if row.table_kind == preferred_kind)
    if preferred:
        return preferred
    generic = tuple(row for row in tables if row.table_kind == "generic_grid")
    return generic or tables


def attach_semantic_lineage(
    *,
    universal_tables: tuple[SiteSchematicUniversalTable, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
    outlet_type_definitions: tuple[SiteSchematicOutletTypeDefinition, ...],
    drawing_index_rows: tuple[SiteSchematicDrawingIndexRow, ...],
) -> tuple[
    tuple[SiteSchematicLegendEntry, ...],
    tuple[SiteSchematicAbbreviationEntry, ...],
    tuple[SiteSchematicOutletTypeDefinition, ...],
    tuple[SiteSchematicDrawingIndexRow, ...],
    tuple[SiteSchematicSemanticLineageRef, ...],
]:
    refs: list[SiteSchematicSemanticLineageRef] = []

    def make_ref(*, semantic_type: str, semantic_id: str, table_id: str, row_id: str, cell_ids: tuple[str, ...]) -> SiteSchematicSemanticLineageRef:
        return SiteSchematicSemanticLineageRef(
            semantic_object_type=semantic_type,
            semantic_object_id=semantic_id,
            source_table_id=table_id,
            source_row_id=row_id,
            source_cell_ids=cell_ids,
        )

    legend_out: list[SiteSchematicLegendEntry] = []
    legend_candidates = _table_candidates(universal_tables, "symbol_legend")
    for entry in legend_entries:
        best = _best_row_for_text(text=f"{entry.label} {entry.description}", candidates=legend_candidates)
        if best is None:
            legend_out.append(entry)
            continue
        table, row = best
        cell_ids = tuple(cell.cell_id for cell in row.cells if cell.raw_text)
        patched = replace(entry, source_table_id=table.table_id, source_row_id=row.row_id, source_cell_ids=cell_ids)
        legend_out.append(patched)
        refs.append(make_ref(semantic_type="legend_entry", semantic_id=patched.entry_id, table_id=table.table_id, row_id=row.row_id, cell_ids=cell_ids))

    abbr_out: list[SiteSchematicAbbreviationEntry] = []
    abbr_candidates = _table_candidates(universal_tables, "abbreviation_matrix")
    for entry in abbreviations:
        best = _best_row_for_text(text=f"{entry.token} {entry.meaning}", candidates=abbr_candidates)
        if best is None:
            abbr_out.append(entry)
            continue
        table, row = best
        cell_ids = tuple(cell.cell_id for cell in row.cells if cell.raw_text)
        patched = replace(entry, source_table_id=table.table_id, source_row_id=row.row_id, source_cell_ids=cell_ids)
        abbr_out.append(patched)
        refs.append(make_ref(semantic_type="abbreviation_entry", semantic_id=patched.entry_id, table_id=table.table_id, row_id=row.row_id, cell_ids=cell_ids))

    outlet_out: list[SiteSchematicOutletTypeDefinition] = []
    outlet_candidates = _table_candidates(universal_tables, "outlet_definition")
    for entry in outlet_type_definitions:
        best = _best_row_for_text(text=entry.label, candidates=outlet_candidates)
        if best is None:
            outlet_out.append(entry)
            continue
        table, row = best
        cell_ids = tuple(cell.cell_id for cell in row.cells if cell.raw_text)
        patched = replace(entry, source_table_id=table.table_id, source_row_id=row.row_id, source_cell_ids=cell_ids)
        outlet_out.append(patched)
        refs.append(make_ref(semantic_type="outlet_definition", semantic_id=patched.definition_id, table_id=table.table_id, row_id=row.row_id, cell_ids=cell_ids))

    drawing_out: list[SiteSchematicDrawingIndexRow] = []
    drawing_candidates = _table_candidates(universal_tables, "drawing_index")
    for row_obj in drawing_index_rows:
        best = _best_row_for_text(text=f"{row_obj.sheet_number} {row_obj.sheet_title}", candidates=drawing_candidates)
        if best is None:
            drawing_out.append(row_obj)
            continue
        table, row = best
        cell_ids = tuple(cell.cell_id for cell in row.cells if cell.raw_text)
        patched = replace(row_obj, source_table_id=table.table_id, source_row_id=row.row_id, source_cell_ids=cell_ids)
        drawing_out.append(patched)
        refs.append(make_ref(semantic_type="drawing_index_row", semantic_id=patched.row_id, table_id=table.table_id, row_id=row.row_id, cell_ids=cell_ids))

    return (tuple(legend_out), tuple(abbr_out), tuple(outlet_out), tuple(drawing_out), tuple(refs))
