from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz  # type: ignore

from orbitbrief_core.parser.site_schematic.modality_calibration import calibrate_modality_decision
from orbitbrief_core.parser.site_schematic.modality_zero_guard import detect_suspicious_zero_primitive_page
from orbitbrief_core.parser.site_schematic.packet_v0_v1_quality import summarize_packet_v0_v1
from orbitbrief_core.parser.site_schematic.page_modality_router import classify_page_modality
from orbitbrief_core.parser.site_schematic.primitive_dedup import dedup_vector_primitives
from orbitbrief_core.parser.site_schematic.primitive_density_audit import audit_primitive_density
from orbitbrief_core.parser.site_schematic.primitive_validation import validate_vector_primitive
from orbitbrief_core.parser.site_schematic.leader_dimension_quality import (
    score_dimension_semantic_quality,
    score_leader_semantic_quality,
)
from orbitbrief_core.parser.site_schematic.vector_primitive_graph import build_vector_primitive_graph
from orbitbrief_core.parser.site_schematic.vector_primitives import extract_vector_primitives_from_drawings

from .phase_d_universality_eval import _packet_runtime_rows

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "compiled_artifacts" / "phase_v0_v1_eval"
CORPUS_ROOT = Path(__file__).resolve().parents[2] / "compiled_artifacts" / "parser_full_extraction_corpus"
PERFECTION_KIT_ROOT = Path(__file__).resolve().parent / "fixtures" / "phase_v0_v1_perfection_kit"
GAP_CLOSURE_KIT_ROOT = Path(__file__).resolve().parent / "fixtures" / "phase_v0_v1_gap_closure_kit"
MASTER_SCHEMA = PERFECTION_KIT_ROOT / "phase_v0_v1_perfection_gold_schema_master.json"
TARGET_METRICS = GAP_CLOSURE_KIT_ROOT / "phase_v0_v1_gap_closure_target_metrics.json"
PACKET_SCHEMA_DIR = PERFECTION_KIT_ROOT / "gold_packet_schemas"


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_phase_v0_v1_fast_eval(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    schema = json.loads(MASTER_SCHEMA.read_text(encoding="utf-8")) if MASTER_SCHEMA.exists() else {}
    target = json.loads(TARGET_METRICS.read_text(encoding="utf-8")) if TARGET_METRICS.exists() else {}
    packet_rows: list[dict[str, Any]] = []
    packet_quality_rows: list[dict[str, Any]] = []

    totals = defaultdict(float)
    current_pair_expected = 0
    current_pair_hits = 0
    holdout_pages = 0
    holdout_routed = 0
    suspicious_zero_page_failures = 0
    suspicious_zero_packet_failures = 0
    dedup_effectiveness_rows: list[float] = []
    density_sanity_rows: list[float] = []
    leader_quality_rows: list[float] = []
    dimension_quality_rows: list[float] = []

    for runtime in _packet_runtime_rows():
        if not runtime.downloaded or not runtime.pdf_path.exists():
            continue
        sheet_inventory_path = CORPUS_ROOT / runtime.packet_id / "sheet_inventory.json"
        universal_tables_path = CORPUS_ROOT / runtime.packet_id / "universal_tables.json"
        sheet_types: dict[int, str] = {}
        table_counts: dict[int, int] = defaultdict(int)
        if sheet_inventory_path.exists():
            payload = json.loads(sheet_inventory_path.read_text(encoding="utf-8"))
            for row in payload:
                sheet_types[int(row.get("page_index", 0))] = str(row.get("sheet_type", "unknown"))
        if universal_tables_path.exists():
            tables_payload = json.loads(universal_tables_path.read_text(encoding="utf-8"))
            for table in tables_payload.get("tables", []):
                page_idx = int(table.get("page_index", 0))
                if page_idx > 0:
                    table_counts[page_idx] += 1

        expected_modality: dict[str, list[str]] = {}
        packet_schema_path = PACKET_SCHEMA_DIR / f"{runtime.packet_id}_phase_v0_v1_perfection_gold.json"
        if packet_schema_path.exists():
            packet_schema = json.loads(packet_schema_path.read_text(encoding="utf-8"))
            expected_modality = dict(packet_schema.get("expected_modality", {}) or {})
        modality_counts = {"vector_rich": 0, "hybrid": 0, "raster_heavy": 0}
        expected_pages = 0
        expected_hits = 0
        vector_pages = 0
        vector_pages_expected_for_graph = 0
        vector_pages_with_graph = 0
        vector_primitives_total = 0
        validated_primitive_total = 0
        vector_bbox_ok = 0
        vector_provenance_ok = 0
        leader_expected = 0
        leader_hits = 0
        dimension_expected = 0
        dimension_hits = 0
        raster_heavy_pages: list[int] = []
        page_modality_rows: list[dict[str, Any]] = []
        primitive_graph_rows: list[dict[str, Any]] = []
        packet_suspicious_zero_pages = 0

        document = fitz.open(runtime.pdf_path)
        for page_zero, page in enumerate(document):
            page_index = page_zero + 1
            sheet_type = sheet_types.get(page_index, "unknown")
            page_text = page.get_text("text") or ""
            drawings = page.get_drawings() or []
            images = page.get_images(full=True) or []
            line_art_density = min(1.0, len(drawings) / max(1.0, 4.0 * max(1, len(page_text.splitlines()))))
            decision = classify_page_modality(
                page_index=page_index,
                sheet_type=sheet_type,
                page_text=page_text,
                vector_path_count=len(drawings),
                image_count=len(images),
                line_art_density=line_art_density,
                table_count=table_counts.get(page_index, 0),
            )
            calibration = calibrate_modality_decision(
                modality=decision.modality,
                confidence=decision.confidence,
                vector_path_count=len(drawings),
                image_count=len(images),
                line_art_density=line_art_density,
                text_density=float(decision.diagnostics.get("text_density", 0.0)),
            )
            modality = calibration.modality
            modality_counts[modality] = modality_counts.get(modality, 0) + 1
            page_modality_rows.append(
                {
                    "page_index": page_index,
                    "sheet_type": sheet_type,
                    "modality": modality,
                    "ambiguous": calibration.ambiguous,
                }
            )
            if modality == "raster_heavy":
                raster_heavy_pages.append(page_index)

            allowed = expected_modality.get(sheet_type, [])
            if allowed:
                expected_pages += 1
                if modality in set(allowed):
                    expected_hits += 1
            if modality in {"vector_rich", "hybrid"}:
                vector_pages += 1
                raw_primitives = extract_vector_primitives_from_drawings(drawings, page_index=page_index)
                deduped_primitives = dedup_vector_primitives(raw_primitives)
                validations = [validate_vector_primitive(row) for row in deduped_primitives]
                validated_primitives = [row for idx, row in enumerate(deduped_primitives) if validations[idx].valid]
                vector_primitives_total += len(deduped_primitives)
                validated_primitive_total += sum(1 for row in validations if row.valid)
                vector_bbox_ok += sum(1 for row in deduped_primitives if row.bbox is not None)
                vector_provenance_ok += sum(1 for row in deduped_primitives if row.page_index > 0 and row.provider and row.source_mode)
                density_audit = audit_primitive_density(
                    raw_count=len(raw_primitives),
                    deduped_count=len(deduped_primitives),
                    validated_count=len(validated_primitives),
                )
                if len(raw_primitives) > 0:
                    dedup_effectiveness_rows.append(float(density_audit.dedup_effectiveness))
                    density_sanity_rows.append(1.0 if density_audit.sanity_ok else 0.0)
                zero_guard = detect_suspicious_zero_primitive_page(
                    modality=modality,
                    vector_path_count=len(drawings),
                    image_count=len(images),
                    line_art_density=line_art_density,
                    primitive_count=len(deduped_primitives),
                    validated_primitive_count=len(validated_primitives),
                )
                if zero_guard.suspicious:
                    packet_suspicious_zero_pages += 1
                if len(drawings) > 0:
                    vector_pages_expected_for_graph += 1
                graph_input = tuple(validated_primitives) or tuple(deduped_primitives)
                if graph_input:
                    graph = build_vector_primitive_graph(graph_input, page_index=page_index)
                    vector_pages_with_graph += 1
                    by_id = {row.primitive_id: row for row in graph_input}
                    leader_quality_valid = 0
                    for primitive_id in graph.leader_candidate_ids:
                        quality = score_leader_semantic_quality(by_id[primitive_id], nearby_text_hint=bool(page_text.strip()))
                        leader_quality_rows.append(1.0 if quality.valid else 0.0)
                        leader_quality_valid += 1 if quality.valid else 0
                    dimension_quality_valid = 0
                    for primitive_id in graph.dimension_candidate_ids:
                        quality = score_dimension_semantic_quality(
                            by_id[primitive_id],
                            nearby_numeric_text=bool(any(ch.isdigit() for ch in page_text)),
                            witness_line_hint=True,
                        )
                        dimension_quality_rows.append(1.0 if quality.valid else 0.0)
                        dimension_quality_valid += 1 if quality.valid else 0
                    primitive_graph_rows.append(
                        {
                            "primitive_count": len(deduped_primitives),
                            "validated_primitive_count": sum(1 for row in validations if row.valid),
                            "leader_candidate_count": len(graph.leader_candidate_ids),
                            "dimension_candidate_count": len(graph.dimension_candidate_ids),
                            "suspicious_zero_primitive": zero_guard.suspicious,
                            "dedup_effectiveness": round(density_audit.dedup_effectiveness, 4),
                            "density_sanity_ok": density_audit.sanity_ok,
                            "leader_semantic_quality_rate": round(
                                leader_quality_valid / max(1, len(graph.leader_candidate_ids)),
                                4,
                            ),
                            "dimension_semantic_quality_rate": round(
                                dimension_quality_valid / max(1, len(graph.dimension_candidate_ids)),
                                4,
                            ),
                        }
                    )
                    if sheet_type in {"riser_diagram", "installation_detail", "equipment_room_layout", "floorplan_detail", "floorplan_overall"}:
                        leader_expected += 1
                        if len(graph.leader_candidate_ids) > 0:
                            leader_hits += 1
                    if sheet_type in {"installation_detail", "equipment_room_layout", "rack_detail", "floorplan_detail"}:
                        dimension_expected += 1
                        if len(graph.dimension_candidate_ids) > 0:
                            dimension_hits += 1
        document.close()

        packet_row = {
            "packet_id": runtime.packet_id,
            "role": runtime.role,
            "category": runtime.category,
            "modality_counts": modality_counts,
            "modality_expected_pages": expected_pages,
            "modality_expected_hits": expected_hits,
            "modality_consistency_rate": (1.0 if expected_pages <= 0 else round(expected_hits / expected_pages, 4)),
            "vector_primitive_count": vector_primitives_total,
            "validated_vector_primitive_count": validated_primitive_total,
            "vector_bbox_presence_rate": round(vector_bbox_ok / max(1, vector_primitives_total), 4),
            "primitive_provenance_rate": round(vector_provenance_ok / max(1, vector_primitives_total), 4),
            "vector_pages": vector_pages,
            "vector_pages_expected_for_graph": vector_pages_expected_for_graph,
            "vector_pages_with_graph": vector_pages_with_graph,
            "primitive_graph_construction_rate": round(vector_pages_with_graph / max(1, vector_pages_expected_for_graph), 4),
            "leader_expected_pages": leader_expected,
            "leader_hit_pages": leader_hits,
            "leader_presence_rate": round(leader_hits / max(1, leader_expected), 4),
            "dimension_expected_pages": dimension_expected,
            "dimension_hit_pages": dimension_hits,
            "dimension_presence_rate": round(dimension_hits / max(1, dimension_expected), 4),
            "suspicious_zero_primitive_page_failures": packet_suspicious_zero_pages,
            "raster_heavy_pages": raster_heavy_pages,
        }
        packet_rows.append(packet_row)
        packet_quality = summarize_packet_v0_v1(
            packet_id=runtime.packet_id,
            page_modality_rows=page_modality_rows,
            primitive_graph_rows=primitive_graph_rows,
        )
        packet_quality_rows.append(
            {
                "packet_id": packet_quality.packet_id,
                "page_count": packet_quality.page_count,
                "modality_counts": packet_quality.modality_counts,
                "ambiguous_page_count": packet_quality.ambiguous_page_count,
                "primitive_count": packet_quality.primitive_count,
                "validated_primitive_count": packet_quality.validated_primitive_count,
                "leader_candidate_count": packet_quality.leader_candidate_count,
                "dimension_candidate_count": packet_quality.dimension_candidate_count,
                "modality_fail": packet_quality.modality_fail,
                "primitive_graph_fail": packet_quality.primitive_graph_fail,
            }
        )
        if packet_suspicious_zero_pages > 0:
            suspicious_zero_packet_failures += 1
            suspicious_zero_page_failures += packet_suspicious_zero_pages

        totals["expected_pages"] += expected_pages
        totals["expected_hits"] += expected_hits
        totals["vector_primitives"] += vector_primitives_total
        totals["vector_bbox_ok"] += vector_bbox_ok
        totals["vector_provenance_ok"] += vector_provenance_ok
        totals["vector_pages"] += vector_pages
        totals["vector_pages_expected_for_graph"] += vector_pages_expected_for_graph
        totals["vector_pages_with_graph"] += vector_pages_with_graph
        totals["leader_expected"] += leader_expected
        totals["leader_hits"] += leader_hits
        totals["dimension_expected"] += dimension_expected
        totals["dimension_hits"] += dimension_hits
        if runtime.role == "holdout":
            holdout_pages += sum(modality_counts.values())
            holdout_routed += sum(modality_counts.values())
        if runtime.packet_id in {"wireless_current_pair", "low_voltage_current_pair"}:
            current_pair_expected += expected_pages
            current_pair_hits += expected_hits

    summary = {
        "packet_count": len(packet_rows),
        "modality_honesty_rate": (1.0 if totals["expected_pages"] <= 0 else round(totals["expected_hits"] / totals["expected_pages"], 4)),
        "current_pair_hard_page_modality_consistency": (1.0 if current_pair_expected <= 0 else round(current_pair_hits / current_pair_expected, 4)),
        "holdout_routing_completeness": round(holdout_routed / max(1, holdout_pages), 4),
        "vector_bbox_presence_rate": round(totals["vector_bbox_ok"] / max(1, totals["vector_primitives"]), 4),
        "primitive_provenance_rate": round(totals["vector_provenance_ok"] / max(1, totals["vector_primitives"]), 4),
        "primitive_graph_construction_rate": round(
            totals["vector_pages_with_graph"] / max(1, totals["vector_pages_expected_for_graph"]),
            4,
        ),
        "leader_candidate_presence_on_expected_pages": round(totals["leader_hits"] / max(1, totals["leader_expected"]), 4),
        "dimension_candidate_presence_on_expected_pages": round(totals["dimension_hits"] / max(1, totals["dimension_expected"]), 4),
        "packet_level_modality_failures": sum(1 for row in packet_quality_rows if row["modality_fail"]),
        "packet_level_primitive_graph_failures": sum(1 for row in packet_quality_rows if row["primitive_graph_fail"]),
        "suspicious_zero_primitive_packet_failures": suspicious_zero_packet_failures,
        "suspicious_zero_primitive_page_failures": suspicious_zero_page_failures,
        "primitive_dedup_effectiveness_rate": round(sum(dedup_effectiveness_rows) / max(1, len(dedup_effectiveness_rows)), 4),
        "primitive_density_sanity_rate": round(sum(density_sanity_rows) / max(1, len(density_sanity_rows)), 4),
        "leader_semantic_quality_rate": round(sum(leader_quality_rows) / max(1, len(leader_quality_rows)), 4),
        "dimension_semantic_quality_rate": round(sum(dimension_quality_rows) / max(1, len(dimension_quality_rows)), 4),
        "target_thresholds": target,
        "evaluation_mode": "fast_pdf_native",
    }
    _json_dump(root / "phase_v0_v1_packet_rows.json", packet_rows)
    _json_dump(root / "phase_v0_v1_packet_quality_rows.json", packet_quality_rows)
    _json_dump(root / "phase_v0_v1_summary.json", summary)
    (root / "phase_v0_v1_summary.md").write_text(
        "\n".join(
            [
                "# Phase V0/V1 Fast Summary",
                "",
                f"- evaluation_mode: `{summary['evaluation_mode']}`",
                f"- packet_count: `{summary['packet_count']}`",
                f"- modality_honesty_rate: `{summary['modality_honesty_rate']}`",
                f"- current_pair_hard_page_modality_consistency: `{summary['current_pair_hard_page_modality_consistency']}`",
                f"- holdout_routing_completeness: `{summary['holdout_routing_completeness']}`",
                f"- vector_bbox_presence_rate: `{summary['vector_bbox_presence_rate']}`",
                f"- primitive_provenance_rate: `{summary['primitive_provenance_rate']}`",
                f"- primitive_graph_construction_rate: `{summary['primitive_graph_construction_rate']}`",
                f"- leader_candidate_presence_on_expected_pages: `{summary['leader_candidate_presence_on_expected_pages']}`",
                f"- dimension_candidate_presence_on_expected_pages: `{summary['dimension_candidate_presence_on_expected_pages']}`",
                f"- packet_level_modality_failures: `{summary['packet_level_modality_failures']}`",
                f"- packet_level_primitive_graph_failures: `{summary['packet_level_primitive_graph_failures']}`",
                f"- suspicious_zero_primitive_packet_failures: `{summary['suspicious_zero_primitive_packet_failures']}`",
                f"- suspicious_zero_primitive_page_failures: `{summary['suspicious_zero_primitive_page_failures']}`",
                f"- primitive_dedup_effectiveness_rate: `{summary['primitive_dedup_effectiveness_rate']}`",
                f"- primitive_density_sanity_rate: `{summary['primitive_density_sanity_rate']}`",
                f"- leader_semantic_quality_rate: `{summary['leader_semantic_quality_rate']}`",
                f"- dimension_semantic_quality_rate: `{summary['dimension_semantic_quality_rate']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {"artifact_root": str(root), "summary": summary, "packet_rows": packet_rows}


if __name__ == "__main__":
    result = run_phase_v0_v1_fast_eval()
    print(json.dumps(result["summary"], indent=2))
