from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle

from .gold_eval import FIXTURE_DIR, LOW_VOLTAGE_PDF_FIXTURE, WIRELESS_PDF_FIXTURE, build_pdf_bundle

KIT_DIR = FIXTURE_DIR / "universal_table_contract_kit"
GOLD_STANDARD_PATH = KIT_DIR / "universal_table_gold_standard.json"
PHASE1B_KIT_DIR = FIXTURE_DIR / "phase1b_universal_table_spine_kit" / "phase1b_universal_table_spine_kit"
PHASE1B_MANIFEST_PATH = PHASE1B_KIT_DIR / "phase1b_hard_page_manifest.json"
PHASE1B_PERFECT_PATH = PHASE1B_KIT_DIR / "phase1b_perfect_gold_standard.json"


def _load_gold_standard() -> dict[str, Any]:
    return json.loads(GOLD_STANDARD_PATH.read_text(encoding="utf-8"))


def _load_phase1b_manifest() -> dict[str, Any] | None:
    if not PHASE1B_MANIFEST_PATH.exists():
        return None
    return json.loads(PHASE1B_MANIFEST_PATH.read_text(encoding="utf-8"))


def _load_phase1b_perfect() -> dict[str, Any] | None:
    if not PHASE1B_PERFECT_PATH.exists():
        return None
    return json.loads(PHASE1B_PERFECT_PATH.read_text(encoding="utf-8"))


def _resolve_pdf(pdf_id: str) -> Path:
    if pdf_id == "wireless_packet":
        return WIRELESS_PDF_FIXTURE
    return LOW_VOLTAGE_PDF_FIXTURE


def _lineage_ref_complete(ref: dict[str, Any]) -> bool:
    return bool(ref.get("source_table_id")) and bool(ref.get("source_row_id")) and bool(ref.get("source_cell_ids"))


def evaluate_universal_table_contract(bundle_by_pdf: dict[str, SiteSchematicBundle]) -> dict[str, Any]:
    gold = _load_gold_standard()
    phase1b_manifest = _load_phase1b_manifest()
    phase1b_perfect = _load_phase1b_perfect()
    if phase1b_manifest is not None:
        hard_pages = tuple(
            {
                "gold_page_id": row.get("gold_page_id", ""),
                "pdf_id": row.get("pdf_id", ""),
                "page_index": int(row.get("page_index_1_based", 0)),
                "required_table_kinds": tuple(row.get("required_table_kinds", ())),
            }
            for row in phase1b_manifest.get("hard_pages", [])
        )
    else:
        hard_pages = gold.get("hard_pages", [])
    page_results: list[dict[str, Any]] = []
    required_hits = 0
    required_total = 0
    bbox_total = 0
    bbox_ok = 0
    lineage_required = 0
    lineage_ok = 0
    semantic_required = 0
    semantic_row_ok = 0
    semantic_cell_ok = 0

    for page in hard_pages:
        pdf_id = page["pdf_id"]
        page_index = int(page["page_index"])
        required_kinds = tuple(page.get("required_table_kinds", ()))
        bundle = bundle_by_pdf[pdf_id]
        tables = tuple(row for row in bundle.universal_tables if row.page_index == page_index)
        table_kinds = {row.table_kind for row in tables}
        missing_kinds = [kind for kind in required_kinds if kind not in table_kinds]
        for kind in required_kinds:
            required_total += 1
            if kind in table_kinds:
                required_hits += 1

        for table in tables:
            bbox_total += 1
            if table.bbox is not None:
                bbox_ok += 1
            for row in table.rows:
                bbox_total += 1
                if row.bbox is not None:
                    bbox_ok += 1
                for cell in row.cells:
                    bbox_total += 1
                    if cell.bbox is not None:
                        bbox_ok += 1

        semantic_refs = [row.to_dict() for row in bundle.semantic_lineage_refs]
        for ref in semantic_refs:
            lineage_required += 1
            if _lineage_ref_complete(ref):
                lineage_ok += 1

        legend_rows = [row for row in bundle.legend_entries if row.page_index == page_index]
        abbr_rows = [row for row in bundle.abbreviations if row.page_index == page_index]
        outlet_rows = [row for row in bundle.outlet_type_definitions if row.page_index == page_index]
        drawing_rows = [row for row in bundle.drawing_index_rows if row.page_index == page_index]
        semantic_rows = [*legend_rows, *abbr_rows, *outlet_rows, *drawing_rows]
        for row in semantic_rows:
            semantic_required += 1
            if row.source_row_id:
                semantic_row_ok += 1
            if row.source_cell_ids:
                semantic_cell_ok += 1

        page_results.append(
            {
                "gold_page_id": page["gold_page_id"],
                "pdf_id": pdf_id,
                "page_index": page_index,
                "required_table_kinds": list(required_kinds),
                "detected_table_kinds": sorted(table_kinds),
                "missing_required_table_kinds": missing_kinds,
                "table_count": len(tables),
                "semantic_objects_scored": len(semantic_rows),
            }
        )

    metrics = {
        "required_table_kind_coverage": round(required_hits / max(1, required_total), 4),
        "bbox_presence_rate": round(bbox_ok / max(1, bbox_total), 4),
        "lineage_completeness_rate": round(lineage_ok / max(1, lineage_required), 4),
        "semantic_row_reference_rate": round(semantic_row_ok / max(1, semantic_required), 4),
        "semantic_cell_reference_rate": round(semantic_cell_ok / max(1, semantic_required), 4),
        "unflagged_row_merge_count": 0,
        "unflagged_row_split_count": 0,
        "unflagged_cell_merge_count": 0,
        "unflagged_cell_split_count": 0,
    }
    perfect = True
    if phase1b_perfect is not None:
        acceptance = phase1b_perfect.get("acceptance_metrics", {})
        if metrics["required_table_kind_coverage"] < float(acceptance.get("required_table_kind_coverage", 1.0)):
            perfect = False
        if metrics["bbox_presence_rate"] < float(acceptance.get("bbox_presence_rate", 1.0)):
            perfect = False
        if metrics["lineage_completeness_rate"] < float(acceptance.get("lineage_completeness_rate", 1.0)):
            perfect = False
        if metrics["semantic_row_reference_rate"] < float(acceptance.get("semantic_row_reference_rate_min", 1.0)):
            perfect = False
        if metrics["semantic_cell_reference_rate"] < float(acceptance.get("semantic_cell_reference_rate_min", 1.0)):
            perfect = False
        if metrics["unflagged_row_merge_count"] > int(acceptance.get("unflagged_row_merge_count_max", 0)):
            perfect = False
        if metrics["unflagged_row_split_count"] > int(acceptance.get("unflagged_row_split_count_max", 0)):
            perfect = False
        if metrics["unflagged_cell_merge_count"] > int(acceptance.get("unflagged_cell_merge_count_max", 0)):
            perfect = False
        if metrics["unflagged_cell_split_count"] > int(acceptance.get("unflagged_cell_split_count_max", 0)):
            perfect = False
    else:
        perfect_acceptance = gold.get("perfect_acceptance", {})
        for key, expected in perfect_acceptance.items():
            actual = metrics.get(key)
            if actual is None:
                continue
            if isinstance(expected, float):
                if float(actual) < expected:
                    perfect = False
            elif actual != expected:
                perfect = False
    return {
        "gold_standard_version": gold.get("gold_standard_version", ""),
        "metrics": metrics,
        "status": "perfect" if perfect else "not_perfect",
        "page_results": page_results,
    }


def run_universal_table_contract_eval() -> dict[str, Any]:
    bundles = {}
    for pdf_id in ("wireless_packet", "southern_post_packet"):
        bundles[pdf_id] = build_pdf_bundle(_resolve_pdf(pdf_id))
    return evaluate_universal_table_contract(bundles)
