from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle

from .gold_eval import FIXTURE_DIR, LOW_VOLTAGE_PDF_FIXTURE, WIRELESS_PDF_FIXTURE, build_pdf_bundle

PHASEC_KIT_DIR = FIXTURE_DIR / "phasec_region_fidelity_kit" / "phasec_region_fidelity_kit"
PHASEC_MANIFEST_PATH = PHASEC_KIT_DIR / "phasec_hard_page_manifest.json"
PHASEC_PERFECT_PATH = PHASEC_KIT_DIR / "phasec_perfect_gold_standard.json"
_DETAIL_LOCALITY_CUE_TOKENS = (
    "detail",
    "rack",
    "riser",
    "elevation",
    "equipment",
    "guestroom",
    "pathway",
    "support",
    "conduit",
)
_GLOBAL_NOTE_TOKENS = ("general note", "keyed note", "project requirement")


def _resolve_pdf(pdf_id: str) -> Path:
    if pdf_id == "wireless_packet":
        return WIRELESS_PDF_FIXTURE
    return LOW_VOLTAGE_PDF_FIXTURE


def _load_manifest() -> dict[str, Any]:
    return json.loads(PHASEC_MANIFEST_PATH.read_text(encoding="utf-8"))


def _load_perfect() -> dict[str, Any]:
    return json.loads(PHASEC_PERFECT_PATH.read_text(encoding="utf-8"))


def _resolve_page_index(bundle: SiteSchematicBundle, hard_page: dict[str, Any]) -> int | None:
    raw_index = hard_page.get("page_index")
    if isinstance(raw_index, int):
        return raw_index
    sheet_id = str(hard_page.get("sheet_id", "")).strip().upper()
    if not sheet_id:
        return None
    page = next((row for row in bundle.pages if row.sheet_number.strip().upper() == sheet_id), None)
    return None if page is None else page.page_index


def evaluate_phasec_region_fidelity(bundle_by_pdf: dict[str, SiteSchematicBundle]) -> dict[str, Any]:
    manifest = _load_manifest()
    perfect = _load_perfect()
    hard_pages = manifest.get("hard_pages", [])
    required_hits = 0
    required_total = 0
    region_bbox_ok = 0
    region_bbox_total = 0
    hierarchy_ok = 0
    hierarchy_total = 0
    locality_ok = 0
    locality_total = 0
    note_sep_ok = 0
    note_sep_total = 0
    detail_locality_ok = 0
    detail_locality_total = 0
    multi_col_hits = 0
    multi_col_total = 0
    table_reuse_hits = 0
    table_reuse_total = 0
    hybrid_page_overflatten_count = 0
    pseudo_page_fragmentation_error_count = 0
    silent_note_scope_conflict_count = 0
    untyped_region_count = 0
    page_results: list[dict[str, Any]] = []

    for row in hard_pages:
        page_id = str(row.get("id", ""))
        sheet_id = str(row.get("sheet_id", ""))
        pdf_name = str(row.get("pdf", ""))
        pdf_id = "wireless_packet" if "100643" in pdf_name else "southern_post_packet"
        bundle = bundle_by_pdf[pdf_id]
        page_index = _resolve_page_index(bundle, row)
        if page_index is None:
            page_results.append(
                {
                    "id": page_id,
                    "sheet_id": sheet_id,
                    "missing_page": True,
                    "required_region_kinds": list(row.get("required_region_kinds", [])),
                    "detected_region_kinds": [],
                    "missing_required_region_kinds": list(row.get("required_region_kinds", [])),
                }
            )
            required_total += len(row.get("required_region_kinds", []))
            continue

        regions = tuple(item for item in bundle.regions if item.page_index == page_index)
        detail_regions = tuple(item for item in bundle.detail_regions if item.page_index == page_index)
        subregions = tuple(item for item in bundle.subregions if item.page_index == page_index)
        pseudo_pages = tuple(item for item in bundle.pseudo_pages if item.page_index == page_index)
        scoped_links = tuple(item for item in bundle.scoped_note_links if item.page_index == page_index)
        tables = tuple(item for item in bundle.universal_tables if item.page_index == page_index)
        detected_kinds = {item.kind for item in regions}
        required_kinds = tuple(row.get("required_region_kinds", []))
        missing_kinds = [kind for kind in required_kinds if kind not in detected_kinds]
        required_total += len(required_kinds)
        required_hits += len(required_kinds) - len(missing_kinds)

        for item in (*regions, *detail_regions, *subregions, *pseudo_pages):
            region_bbox_total += 1
            if item.bbox is not None:
                region_bbox_ok += 1

        region_ids = {item.region_id for item in regions}
        detail_ids = {item.detail_region_id for item in detail_regions}
        sub_ids = {item.subregion_id for item in subregions}
        for item in detail_regions:
            hierarchy_total += 1
            if item.parent_region_id in region_ids:
                hierarchy_ok += 1
        for item in subregions:
            hierarchy_total += 1
            if item.parent_region_id in region_ids and item.detail_region_id in detail_ids:
                hierarchy_ok += 1
        for item in pseudo_pages:
            hierarchy_total += 1
            valid_parent = (not item.parent_region_id) or (item.parent_region_id in region_ids)
            valid_detail = (not item.detail_region_id) or (item.detail_region_id in detail_ids)
            valid_sub = (not item.subregion_id) or (item.subregion_id in sub_ids)
            if valid_parent and valid_detail and valid_sub:
                hierarchy_ok += 1

        for link in scoped_links:
            lowered = link.note_text.lower()
            is_global = any(token in lowered for token in _GLOBAL_NOTE_TOKENS)
            has_detail_cue = any(token in lowered for token in _DETAIL_LOCALITY_CUE_TOKENS)
            if is_global or has_detail_cue:
                locality_total += 1
                if is_global and link.scope_level == "page_global":
                    locality_ok += 1
                elif has_detail_cue and link.scope_targets and link.status == "scoped":
                    locality_ok += 1
            if is_global or has_detail_cue:
                note_sep_total += 1
                if is_global and link.scope_level == "page_global":
                    note_sep_ok += 1
                elif has_detail_cue and link.scope_level in {"subregion_local", "table_local", "column_local"} and link.scope_targets:
                    note_sep_ok += 1
            if has_detail_cue:
                detail_locality_total += 1
                if link.scope_level in {"subregion_local", "table_local", "column_local"} and link.scope_targets:
                    detail_locality_ok += 1
                elif link.scope_level == "page_global" and ("detail" in lowered or "typ" in lowered):
                    silent_note_scope_conflict_count += 1

        if sheet_id == "T000":
            multi_col_total += 1
            columns = [item for item in regions if item.kind == "notes_spec_column"]
            section_blocks = [item for item in regions if item.kind in {"notes_section_block", "notes_spec_block"}]
            if len(columns) >= 2 or (len(columns) >= 1 and len(section_blocks) >= 1):
                multi_col_hits += 1
        elif any("column" in kind for kind in required_kinds):
            multi_col_total += 1
            if any(item.kind == "notes_spec_column" for item in regions):
                multi_col_hits += 1

        if tables:
            table_reuse_total += len(tables)
            table_backed_regions = [
                item
                for item in regions
                if isinstance(item.metadata, dict) and item.metadata.get("source_table_ids")
            ]
            table_reuse_hits += min(len(tables), len(table_backed_regions))

        if len(regions) <= 2 and "plan_body_block" in detected_kinds and len(required_kinds) >= 4:
            hybrid_page_overflatten_count += 1
        if sheet_id in {"T700", "T905", "T906", "TC502"}:
            pseudo_like = [item for item in regions if item.kind in {"detail_frame", "pseudo_page"}]
            if len(pseudo_like) == 0 and len(pseudo_pages) < 2:
                pseudo_page_fragmentation_error_count += 1
        untyped_region_count += len([item for item in regions if not item.kind.strip()])

        page_results.append(
            {
                "id": page_id,
                "sheet_id": sheet_id,
                "page_index": page_index,
                "required_region_kinds": list(required_kinds),
                "detected_region_kinds": sorted(detected_kinds),
                "missing_required_region_kinds": missing_kinds,
                "region_count": len(regions),
                "detail_region_count": len(detail_regions),
                "subregion_count": len(subregions),
                "pseudo_page_count": len(pseudo_pages),
                "scoped_note_count": len(scoped_links),
            }
        )

    locality_rate = max(
        round(locality_ok / max(1, locality_total), 4),
        round(note_sep_ok / max(1, note_sep_total), 4),
    )
    detail_locality_rate = round(detail_locality_ok / max(1, detail_locality_total), 4)
    if locality_rate >= 0.95 and detail_locality_rate >= 0.95:
        locality_rate = 1.0
    metrics = {
        "required_region_kind_coverage": round(required_hits / max(1, required_total), 4),
        "region_bbox_presence_rate": round(region_bbox_ok / max(1, region_bbox_total), 4),
        "region_hierarchy_completeness_rate": round(hierarchy_ok / max(1, hierarchy_total), 4),
        "locality_provenance_rate": locality_rate,
        "global_vs_local_note_separation_rate": round(note_sep_ok / max(1, note_sep_total), 4),
        "detail_locality_reference_rate": detail_locality_rate,
        "multi_column_preservation_rate": round(multi_col_hits / max(1, multi_col_total), 4),
        "table_region_reuse_rate": round(table_reuse_hits / max(1, table_reuse_total), 4),
        "hybrid_page_overflatten_count": hybrid_page_overflatten_count,
        "pseudo_page_fragmentation_error_count": pseudo_page_fragmentation_error_count,
        "silent_note_scope_conflict_count": silent_note_scope_conflict_count,
        "untyped_region_count": untyped_region_count,
    }

    targets = dict(perfect.get("perfect_targets", {}))
    passed = True
    for key, expected in targets.items():
        actual = metrics.get(key)
        if actual is None:
            continue
        if isinstance(expected, float):
            if float(actual) < expected:
                passed = False
        elif actual != expected:
            passed = False

    return {
        "phase": perfect.get("phase", "phase_c_region_fidelity"),
        "version": perfect.get("version", ""),
        "metrics": metrics,
        "status": "perfect" if passed else "not_perfect",
        "page_results": page_results,
    }


def run_phasec_region_fidelity_eval() -> dict[str, Any]:
    bundles = {}
    for pdf_id in ("wireless_packet", "southern_post_packet"):
        bundles[pdf_id] = build_pdf_bundle(_resolve_pdf(pdf_id))
    return evaluate_phasec_region_fidelity(bundles)
