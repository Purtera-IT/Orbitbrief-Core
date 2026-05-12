from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle, SiteSchematicSymbolCandidateInput
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import build_first_pass_detector_class_map, map_ontology_class_to_detector_class
from orbitbrief_core.parser.site_schematic.symbols.vocabulary import classify_candidate_with_vocabulary, load_universal_symbol_vocabulary


def _is_normalized_bbox(bbox: tuple[float, float, float, float]) -> bool:
    return all(0.0 <= value <= 1.0 for value in bbox)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _to_page_bbox(
    bbox: tuple[float, float, float, float] | None,
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    if _is_normalized_bbox(bbox):
        x0 *= page_width
        x1 *= page_width
        y0 *= page_height
        y1 *= page_height
    x0 = _clamp(float(x0), 0.0, page_width)
    x1 = _clamp(float(x1), 0.0, page_width)
    y0 = _clamp(float(y0), 0.0, page_height)
    y1 = _clamp(float(y1), 0.0, page_height)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def build_symbol_export_sidecar_rows(
    *,
    bundle: SiteSchematicBundle,
    packet_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    vocab = load_universal_symbol_vocabulary()
    detector_map = build_first_pass_detector_class_map()

    def _split(candidate_id: str) -> str:
        value = abs(hash(f"{packet_id}:{candidate_id}")) % 100
        if value < 70:
            return "train"
        if value < 85:
            return "val"
        return "test"

    for candidate in bundle.symbol_candidate_inputs:
        vocabulary = classify_candidate_with_vocabulary(
            packet_id=packet_id,
            local_text=candidate.local_text_context,
            legend_texts=candidate.nearby_legend_texts,
            note_clauses=candidate.nearby_note_clauses,
            abbreviations=candidate.nearby_abbreviations,
        )
        ontology_class_id = str(vocabulary.get("primary_class_id", "unknown"))
        detector = map_ontology_class_to_detector_class(ontology_class_id)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "artifact_id": candidate.artifact_id,
                "packet_id": packet_id,
                "page_index": candidate.page_index,
                "sheet_type": candidate.sheet_type,
                "sheet_number": candidate.sheet_number,
                "sheet_title": candidate.sheet_title,
                "region_id": candidate.region_id,
                "detail_region_id": candidate.detail_region_id,
                "subregion_id": candidate.subregion_id,
                "pseudo_page_id": candidate.pseudo_page_id,
                "bbox": list(candidate.bbox) if candidate.bbox else None,
                "source_mode": candidate.source_mode,
                "provider": candidate.provider,
                "decomposition_confidence": candidate.decomposition_confidence,
                "local_text_context": candidate.local_text_context,
                "nearby_note_clauses": list(candidate.nearby_note_clauses),
                "nearby_legend_entry_ids": list(candidate.nearby_legend_entry_ids),
                "nearby_legend_texts": list(candidate.nearby_legend_texts),
                "nearby_abbreviations": list(candidate.nearby_abbreviations),
                "nearby_room_labels": list(candidate.nearby_room_labels),
                "nearby_closet_labels": list(candidate.nearby_closet_labels),
                "vocabulary_version": vocab.get("vocabulary_version", ""),
                "vocabulary_primary_class_id": vocabulary.get("primary_class_id", "unknown"),
                "vocabulary_primary_modality": vocabulary.get("primary_modality", "unknown"),
                "vocabulary_tier1": vocabulary.get("primary_tier1", ""),
                "vocabulary_tier2": vocabulary.get("primary_tier2", ""),
                "vocabulary_primary_training_plan": vocabulary.get("primary_training_plan", "defer"),
                "vocabulary_primary_merge_parent": vocabulary.get("primary_merge_parent", ""),
                "vocabulary_focus_matched": bool(vocabulary.get("focus_matched", False)),
                "vocabulary_matches": list(vocabulary.get("matches", []))[:6],
                "ontology_primary_class_id": ontology_class_id,
                "detector_class_id": detector.get("detector_class_id"),
                "detector_selection_status": detector.get("selection_status", ""),
                "detector_selected_for_first_pass": bool(detector.get("selected_for_first_pass", False)),
                "detector_split": _split(candidate.candidate_id),
                "metadata": dict(candidate.metadata),
            }
        )
    return rows


def export_symbol_candidate_crops(
    *,
    bundle: SiteSchematicBundle,
    pdf_path: Path,
    output_dir: Path,
    packet_id: str,
    image_scale: float = 2.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    detector_map = build_first_pass_detector_class_map()
    sidecar_rows = build_symbol_export_sidecar_rows(bundle=bundle, packet_id=packet_id)
    sidecar_path = output_dir / "symbol_candidate_metadata.jsonl"
    rendered = 0
    skipped = 0
    render_errors = 0
    page_size_lookup: dict[int, tuple[float, float]] = {}
    page_bbox_lookup: dict[int, list[float]] = {}
    page_image_errors: dict[int, str] = {}
    doc = None
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        for page_index, page in enumerate(doc, start=1):
            page_size_lookup[page_index] = (float(page.rect.width), float(page.rect.height))
            page_bbox_lookup[page_index] = [0.0, 0.0, float(page.rect.width), float(page.rect.height)]
    except Exception as exc:
        page_image_errors[0] = str(exc)
    with sidecar_path.open("w", encoding="utf-8") as handle:
        for row in sidecar_rows:
            page_index = int(row["page_index"])
            bbox = row["bbox"]
            image_rel_path = ""
            crop_page_bbox = None
            full_page_bbox = page_bbox_lookup.get(page_index)
            if doc is not None and bbox is not None and page_index in page_size_lookup and page_index <= len(doc):
                width, height = page_size_lookup[page_index]
                crop_page_bbox = _to_page_bbox(tuple(float(v) for v in bbox), page_width=width, page_height=height)
                if crop_page_bbox is not None:
                    x0, y0, x1, y1 = crop_page_bbox
                    try:
                        page = doc[page_index - 1]
                        import fitz  # type: ignore

                        clip = fitz.Rect(x0, y0, x1, y1)
                        pix = page.get_pixmap(matrix=fitz.Matrix(image_scale, image_scale), clip=clip, alpha=False)
                        image_name = f"{row['candidate_id'].replace(':', '_')}.png"
                        image_path = output_dir / image_name
                        pix.save(str(image_path))
                        image_rel_path = image_name
                        rendered += 1
                    except Exception as exc:
                        render_errors += 1
                        page_image_errors[page_index] = str(exc)
                else:
                    skipped += 1
            else:
                skipped += 1
            enriched = {
                **row,
                "image_path": image_rel_path,
                "crop_bbox_page_coords": list(crop_page_bbox) if crop_page_bbox else None,
                "full_page_bbox": full_page_bbox,
            }
            handle.write(json.dumps(enriched, ensure_ascii=True) + "\n")
    if doc is not None:
        doc.close()
    return {
        "packet_id": packet_id,
        "pdf_path": str(pdf_path),
        "output_dir": str(output_dir),
        "metadata_path": str(sidecar_path),
        "candidate_count": len(sidecar_rows),
        "rendered_crops": rendered,
        "skipped_crops": skipped,
        "render_errors": render_errors,
        "page_image_errors": page_image_errors,
        "contract_version": "symbol_input_v1",
        "vocabulary_version": load_universal_symbol_vocabulary().get("vocabulary_version", ""),
        "detector_map_version": detector_map.get("detector_map_version", ""),
        "detector_class_count": len(detector_map.get("detector_classes", [])),
    }

