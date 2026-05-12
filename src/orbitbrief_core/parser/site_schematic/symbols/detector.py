from __future__ import annotations

import re

from orbitbrief_core.parser.site_schematic.legends.legend_parser import infer_primitive_kind
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicAbbreviationEntry,
    SiteSchematicLegendEntry,
    SiteSchematicPrimitiveDetection,
    SiteSchematicRegion,
    SiteSchematicSymbolInstance,
)
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import map_ontology_class_to_detector_class
from orbitbrief_core.parser.site_schematic.symbols.vocabulary import classify_candidate_with_vocabulary

_TOKEN_RE = re.compile(r"\b(?:AP|WAP|WM|CM|EXT|AV|RS\d+|CIP|CSP\d+|PP|FIC|TV|POS-T|POS-P|WN|ZN|HC|FE|CRD|AR|DA|MKP|SCP|KP|DAM|LM|BH|TCDS|IC180°|360°|[12]M8|HM8)\b")
_NOISE_TOKENS = {
    "UP", "DN", "SCALE", "TITLE", "NUMBER", "MODEL", "PROJECT", "SEAL", "KEYPLAN", "CONSULTANTS",
    "NOTE", "NOTES", "SHEET", "ROOM", "IDF", "MDF", "TC", "T", "ISSUED", "FOR", "CONSTRUCTION",
    "AND", "OR", "THE", "OF", "IN", "ON", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def build_symbol_vocabulary(
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
) -> set[str]:
    vocab = {
        "AP", "WAP", "WM", "CM", "EXT", "AV", "RS1", "RS2", "RS3", "CIP", "CSP2", "CSP3",
        "PP", "FIC", "TV", "POS-T", "POS-P", "WN", "ZN", "HC", "FE", "IC180°", "360°",
    }
    for entry in legend_entries:
        if entry.symbol_token:
            vocab.add(entry.symbol_token.upper())
    for entry in abbreviations:
        if 1 <= len(entry.token) <= 8:
            vocab.add(entry.token.upper())
    return {token for token in vocab if token and token not in _NOISE_TOKENS}


def _bbox_from_token(line_index: int, total_lines: int, start: int, end: int, line_len: int) -> tuple[float, float, float, float]:
    total_lines = max(total_lines, 1)
    line_len = max(line_len, 1)
    y0 = line_index / total_lines
    y1 = min(1.0, (line_index + 1) / total_lines)
    x0 = start / line_len
    x1 = max(x0, min(1.0, end / line_len))
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


def detect_primitive_symbols(
    *,
    page_index: int,
    text: str,
    overlay_tags: tuple[str, ...],
    regions: tuple[SiteSchematicRegion, ...],
    legend_entries: tuple[SiteSchematicLegendEntry, ...],
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...],
    room_labels: tuple[str, ...],
) -> tuple[SiteSchematicSymbolInstance, ...]:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    total_lines = max(len(lines), 1)
    vocab = build_symbol_vocabulary(legend_entries, abbreviations)
    abbr_lookup = {entry.token.upper(): entry for entry in abbreviations}
    legend_by_token: dict[str, SiteSchematicLegendEntry] = {}
    for entry in legend_entries:
        if entry.symbol_token:
            legend_by_token.setdefault(entry.symbol_token.upper(), entry)

    plan_region = next((region for region in regions if region.kind in {"plan_body_block", "detail_block"}), None)
    region_id = plan_region.region_id if plan_region else ""
    rows: list[SiteSchematicSymbolInstance] = []
    counter = 0
    for line_index, line in enumerate(lines):
        # Skip title-block-like lines to avoid noisy repeated words.
        lower_line = line.lower()
        if any(token in lower_line for token in ("condition of use", "consultants:", "seal:", "issued for construction", "sheet no.")):
            continue
        for match in _TOKEN_RE.finditer(line):
            token = match.group(0).upper().strip()
            if token in _NOISE_TOKENS or token.isdigit() or len(token) == 1:
                continue
            if token not in vocab and token not in legend_by_token and token not in abbr_lookup:
                # allow AP-like short tokens if repeated on the line
                if line.count(token) < 1 or token not in {"AP", "CM", "WM", "EXT", "AV", "CIP", "CSP2", "CSP3", "PP", "FIC", "TV"}:
                    continue
            legend_entry = legend_by_token.get(token)
            abbr_entry = abbr_lookup.get(token)
            primitive_kind = legend_entry.primitive_kind if legend_entry else infer_primitive_kind(abbr_entry.meaning if abbr_entry else token)
            confidence = 0.74 if legend_entry else 0.67 if abbr_entry else 0.58
            room_label = next((room for room in room_labels if room and room in line), "")
            counter += 1
            rows.append(
                SiteSchematicSymbolInstance(
                    instance_id=f"sym:p{page_index}:{counter}",
                    page_index=page_index,
                    token=token,
                    primitive_kind=primitive_kind,
                    text=_clean(line),
                    confidence=confidence,
                    overlay_tags=overlay_tags,
                    region_id=region_id,
                    bbox=_bbox_from_token(line_index, total_lines, match.start(), match.end(), len(line)),
                    source_mode="ocr_token_heuristic",
                    line_index=line_index,
                    room_label=room_label,
                    metadata={
                        "legend_entry_id": legend_entry.entry_id if legend_entry else "",
                        "abbreviation_entry_id": abbr_entry.entry_id if abbr_entry else "",
                    },
                )
            )
    # Dedupe by token, line, and bbox projection.
    deduped: list[SiteSchematicSymbolInstance] = []
    seen: set[tuple[int, str, int | None]] = set()
    for row in rows:
        key = (row.page_index, row.token, row.line_index)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return tuple(deduped)


def materialize_symbol_instances_from_detections(
    *,
    detections: tuple[SiteSchematicPrimitiveDetection, ...],
    overlay_tags: tuple[str, ...],
    page_index: int,
    default_region_id: str = "",
) -> tuple[SiteSchematicSymbolInstance, ...]:
    rows: list[SiteSchematicSymbolInstance] = []
    for idx, row in enumerate(detections, start=1):
        if row.page_index != page_index:
            continue
        token = (row.token_hint or row.primitive_family or "UNK").upper()
        primitive_hint = str((row.metadata or {}).get("primitive_kind_hint", "")).strip()
        source_text = str((row.metadata or {}).get("source_text", "")).strip()
        room_label = str((row.metadata or {}).get("room_label", "")).strip()
        rows.append(
            SiteSchematicSymbolInstance(
                instance_id=f"sym_det:p{page_index}:{idx}",
                page_index=page_index,
                token=token,
                primitive_kind=primitive_hint or row.primitive_family or "unknown_symbol",
                text=source_text or token,
                confidence=max(0.0, min(1.0, row.score)),
                overlay_tags=overlay_tags,
                region_id=row.region_id or default_region_id,
                bbox=row.bbox,
                source_mode=row.source_provider,
                parent_region_id=row.region_id,
                pseudo_page_id=row.pseudo_page_id,
                room_label=room_label,
                metadata={
                    "detection_id": row.detection_id,
                    "detail_region_id": row.detail_region_id,
                    "subregion_id": row.subregion_id,
                    **dict(row.metadata),
                },
            )
        )
    return tuple(rows)


def map_symbol_instances_to_primitive_detections(
    *,
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...],
    packet_id: str,
) -> tuple[SiteSchematicPrimitiveDetection, ...]:
    rows: list[SiteSchematicPrimitiveDetection] = []
    for idx, symbol in enumerate(symbol_instances, start=1):
        vocab = classify_candidate_with_vocabulary(
            packet_id=packet_id,
            local_text=symbol.text,
            legend_texts=(),
            note_clauses=(),
            abbreviations=(),
        )
        ontology_class_id = str(vocab.get("primary_class_id", "unknown"))
        detector_map = map_ontology_class_to_detector_class(ontology_class_id)
        detector_class_id = detector_map.get("detector_class_id")
        if not detector_class_id:
            continue
        rows.append(
            SiteSchematicPrimitiveDetection(
                detection_id=f"det:p{symbol.page_index}:{idx}",
                page_index=symbol.page_index,
                primitive_family=str(detector_class_id),
                token_hint=symbol.token,
                bbox=symbol.bbox,
                score=symbol.confidence,
                source_provider="heuristic_detector_bridge_v1",
                region_id=symbol.region_id,
                pseudo_page_id=symbol.pseudo_page_id,
                metadata={
                    "ontology_class_id": ontology_class_id,
                    "detector_class_id": detector_class_id,
                    "selection_status": detector_map.get("selection_status"),
                    "primitive_kind_hint": symbol.primitive_kind,
                    "source_text": symbol.text,
                    "room_label": symbol.room_label,
                    "source_instance_id": symbol.instance_id,
                },
            )
        )
    return tuple(rows)
