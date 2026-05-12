from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.packet_v0_v1_quality import summarize_packet_v0_v1

from .gold_eval import build_pdf_bundle
from .phase_d_universality_eval import _native_only_eval_profile, _packet_runtime_rows

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "compiled_artifacts" / "phase_v0_v1_eval"
PERFECTION_KIT_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase_v0_v1_perfection_kit"
)
GAP_CLOSURE_KIT_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase_v0_v1_gap_closure_kit"
)
MASTER_SCHEMA = PERFECTION_KIT_ROOT / "phase_v0_v1_perfection_gold_schema_master.json"
TARGET_METRICS = GAP_CLOSURE_KIT_ROOT / "phase_v0_v1_gap_closure_target_metrics.json"
PACKET_SCHEMA_DIR = PERFECTION_KIT_ROOT / "gold_packet_schemas"


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _allowed_modality_hit(sheet_type: str, modality: str, expected: dict[str, list[str]]) -> bool:
    allowed = expected.get(sheet_type, [])
    if not allowed:
        return True
    return modality in set(allowed)


def run_phase_v0_v1_eval(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    schema = json.loads(MASTER_SCHEMA.read_text(encoding="utf-8")) if MASTER_SCHEMA.exists() else {}
    target = json.loads(TARGET_METRICS.read_text(encoding="utf-8")) if TARGET_METRICS.exists() else {}
    runtimes = [row for row in _packet_runtime_rows() if row.downloaded and row.pdf_path.exists()]
    packet_rows: list[dict[str, Any]] = []

    total_expected_modality = 0
    total_expected_modality_hits = 0
    total_vector_pages = 0
    total_vector_pages_with_graph = 0
    total_vector_primitives = 0
    total_vector_bbox_ok = 0
    total_vector_provenance_ok = 0
    leader_expected_pages = 0
    leader_hit_pages = 0
    dimension_expected_pages = 0
    dimension_hit_pages = 0
    holdout_total_pages = 0
    holdout_routed_pages = 0
    current_pair_expected = 0
    current_pair_hits = 0
    packet_quality_rows: list[dict[str, Any]] = []
    suspicious_zero_primitive_page_failures = 0
    suspicious_zero_primitive_packet_failures = 0
    dedup_effectiveness_rows: list[float] = []
    density_sanity_rows: list[float] = []
    leader_quality_rows: list[float] = []
    dimension_quality_rows: list[float] = []

    with _native_only_eval_profile():
        for runtime in runtimes:
            bundle = build_pdf_bundle(runtime.pdf_path)
            modality_rows = list(bundle.page_modality_decisions)
            modality_by_page = {row.page_index: row for row in modality_rows}
            graph_by_page = {row.page_index: row for row in bundle.vector_primitive_graphs}
            packet_schema_path = PACKET_SCHEMA_DIR / f"{runtime.packet_id}_phase_v0_v1_perfection_gold.json"
            expected_modality: dict[str, list[str]] = {}
            if packet_schema_path.exists():
                packet_expectation = json.loads(packet_schema_path.read_text(encoding="utf-8"))
                expected_modality = dict(packet_expectation.get("expected_modality", {}) or {})

            modality_counts = {"vector_rich": 0, "hybrid": 0, "raster_heavy": 0}
            packet_expected = 0
            packet_hits = 0
            packet_vector_pages = 0
            packet_vector_pages_with_graph = 0
            packet_leader_expected = 0
            packet_leader_hits = 0
            packet_dimension_expected = 0
            packet_dimension_hits = 0

            for page in bundle.pages:
                decision = modality_by_page.get(page.page_index)
                if decision is None:
                    continue
                modality_counts[decision.modality] = modality_counts.get(decision.modality, 0) + 1
                if page.sheet_type in expected_modality:
                    packet_expected += 1
                    if _allowed_modality_hit(page.sheet_type, decision.modality, expected_modality):
                        packet_hits += 1
                is_vector_page = decision.modality in {"vector_rich", "hybrid"}
                if is_vector_page:
                    packet_vector_pages += 1
                    if page.page_index in graph_by_page:
                        packet_vector_pages_with_graph += 1
                if page.sheet_type in {"riser_diagram", "installation_detail", "equipment_room_layout", "floorplan_detail", "floorplan_overall"} and is_vector_page:
                    packet_leader_expected += 1
                    if page.page_index in graph_by_page and len(graph_by_page[page.page_index].leader_candidate_ids) > 0:
                        packet_leader_hits += 1
                if page.sheet_type in {"installation_detail", "equipment_room_layout", "rack_detail", "floorplan_detail"} and is_vector_page:
                    packet_dimension_expected += 1
                    if page.page_index in graph_by_page and len(graph_by_page[page.page_index].dimension_candidate_ids) > 0:
                        packet_dimension_hits += 1

            packet_vector_primitives = len(bundle.vector_primitives)
            packet_vector_bbox_ok = sum(1 for row in bundle.vector_primitives if row.bbox is not None)
            packet_vector_provenance_ok = sum(
                1
                for row in bundle.vector_primitives
                if row.source_mode and row.provider and row.page_index > 0
            )
            packet_row = {
            "packet_id": runtime.packet_id,
            "role": runtime.role,
            "category": runtime.category,
            "page_count": bundle.page_count,
            "modality_counts": modality_counts,
            "modality_expected_pages": packet_expected,
            "modality_expected_hits": packet_hits,
            "modality_consistency_rate": (1.0 if packet_expected <= 0 else round(packet_hits / packet_expected, 4)),
            "vector_primitive_count": packet_vector_primitives,
            "vector_bbox_presence_rate": round(packet_vector_bbox_ok / max(1, packet_vector_primitives), 4),
            "primitive_provenance_rate": round(packet_vector_provenance_ok / max(1, packet_vector_primitives), 4),
            "vector_pages": packet_vector_pages,
            "vector_pages_with_graph": packet_vector_pages_with_graph,
            "primitive_graph_construction_rate": round(packet_vector_pages_with_graph / max(1, packet_vector_pages), 4),
            "leader_expected_pages": packet_leader_expected,
            "leader_hit_pages": packet_leader_hits,
            "leader_presence_rate": round(packet_leader_hits / max(1, packet_leader_expected), 4),
            "dimension_expected_pages": packet_dimension_expected,
            "dimension_hit_pages": packet_dimension_hits,
            "dimension_presence_rate": round(packet_dimension_hits / max(1, packet_dimension_expected), 4),
            "pages_routed": len(modality_rows),
            "pages_with_no_vector_content": sum(
                1 for page in bundle.pages if len([row for row in bundle.vector_primitives if row.page_index == page.page_index]) == 0
            ),
            "raster_heavy_pages": [
                page.page_index
                for page in bundle.pages
                if modality_by_page.get(page.page_index) and modality_by_page[page.page_index].modality == "raster_heavy"
            ],
            "ready_for_next_graphics_layer": bool(
                (packet_vector_pages == 0 or packet_vector_pages_with_graph / max(1, packet_vector_pages) >= 0.9)
                and (packet_vector_primitives == 0 or packet_vector_bbox_ok / max(1, packet_vector_primitives) >= 0.99)
            ),
            }
            packet_rows.append(packet_row)
            phase_v0_v1_diag = dict((bundle.model_registry or {}).get("phase_v0_v1", {}) or {})
            suspicious_zero_primitive_page_failures += int(phase_v0_v1_diag.get("suspicious_zero_primitive_page_failures", 0) or 0)
            suspicious_zero_primitive_packet_failures += int(phase_v0_v1_diag.get("suspicious_zero_primitive_packet_failures", 0) or 0)
            dedup_effectiveness_rows.append(float(phase_v0_v1_diag.get("primitive_dedup_effectiveness_rate", 1.0) or 1.0))
            density_sanity_rows.append(float(phase_v0_v1_diag.get("primitive_density_sanity_rate", 1.0) or 1.0))
            leader_quality_rows.append(float(phase_v0_v1_diag.get("leader_semantic_quality_rate", 1.0) or 1.0))
            dimension_quality_rows.append(float(phase_v0_v1_diag.get("dimension_semantic_quality_rate", 1.0) or 1.0))
            packet_summary_obj = bundle.packet_v0_v1_summary
            if packet_summary_obj is None:
                packet_summary_obj = summarize_packet_v0_v1(
                    packet_id=runtime.packet_id,
                    page_modality_rows=[row.to_dict() for row in bundle.page_modality_decisions],
                    primitive_graph_rows=[
                        {
                            "primitive_count": int(row.diagnostics.get("primitive_count", 0.0)),
                            "validated_primitive_count": int(row.diagnostics.get("validated_primitive_count", row.diagnostics.get("primitive_count", 0.0))),
                            "leader_candidate_count": len(row.leader_candidate_ids),
                            "dimension_candidate_count": len(row.dimension_candidate_ids),
                            "suspicious_zero_primitive": bool(row.diagnostics.get("suspicious_zero_primitive", 0.0)),
                        }
                        for row in bundle.vector_primitive_graphs
                    ],
                )
            packet_quality_rows.append(
                {
                    "packet_id": packet_summary_obj.packet_id,
                    "page_count": packet_summary_obj.page_count,
                    "modality_counts": dict(packet_summary_obj.modality_counts),
                    "ambiguous_page_count": packet_summary_obj.ambiguous_page_count,
                    "primitive_count": packet_summary_obj.primitive_count,
                    "validated_primitive_count": packet_summary_obj.validated_primitive_count,
                    "leader_candidate_count": packet_summary_obj.leader_candidate_count,
                    "dimension_candidate_count": packet_summary_obj.dimension_candidate_count,
                    "modality_fail": packet_summary_obj.modality_fail,
                    "primitive_graph_fail": packet_summary_obj.primitive_graph_fail,
                }
            )

            total_expected_modality += packet_expected
            total_expected_modality_hits += packet_hits
            total_vector_pages += packet_vector_pages
            total_vector_pages_with_graph += packet_vector_pages_with_graph
            total_vector_primitives += packet_vector_primitives
            total_vector_bbox_ok += packet_vector_bbox_ok
            total_vector_provenance_ok += packet_vector_provenance_ok
            leader_expected_pages += packet_leader_expected
            leader_hit_pages += packet_leader_hits
            dimension_expected_pages += packet_dimension_expected
            dimension_hit_pages += packet_dimension_hits
            if runtime.role == "holdout":
                holdout_total_pages += bundle.page_count
                holdout_routed_pages += len(modality_rows)
            if runtime.packet_id in {"wireless_current_pair", "low_voltage_current_pair"}:
                current_pair_expected += packet_expected
                current_pair_hits += packet_hits

    summary = {
        "packet_count": len(packet_rows),
        "modality_honesty_rate": (1.0 if total_expected_modality <= 0 else round(total_expected_modality_hits / total_expected_modality, 4)),
        "current_pair_hard_page_modality_consistency": (1.0 if current_pair_expected <= 0 else round(current_pair_hits / current_pair_expected, 4)),
        "holdout_routing_completeness": round(holdout_routed_pages / max(1, holdout_total_pages), 4),
        "vector_bbox_presence_rate": round(total_vector_bbox_ok / max(1, total_vector_primitives), 4),
        "primitive_provenance_rate": round(total_vector_provenance_ok / max(1, total_vector_primitives), 4),
        "primitive_graph_construction_rate": round(total_vector_pages_with_graph / max(1, total_vector_pages), 4),
        "leader_candidate_presence_on_expected_pages": round(leader_hit_pages / max(1, leader_expected_pages), 4),
        "dimension_candidate_presence_on_expected_pages": round(dimension_hit_pages / max(1, dimension_expected_pages), 4),
        "packet_level_modality_failures": sum(1 for row in packet_quality_rows if row["modality_fail"]),
        "packet_level_primitive_graph_failures": sum(1 for row in packet_quality_rows if row["primitive_graph_fail"]),
        "suspicious_zero_primitive_page_failures": suspicious_zero_primitive_page_failures,
        "suspicious_zero_primitive_packet_failures": suspicious_zero_primitive_packet_failures,
        "primitive_dedup_effectiveness_rate": round(sum(dedup_effectiveness_rows) / max(1, len(dedup_effectiveness_rows)), 4),
        "primitive_density_sanity_rate": round(sum(density_sanity_rows) / max(1, len(density_sanity_rows)), 4),
        "leader_semantic_quality_rate": round(sum(leader_quality_rows) / max(1, len(leader_quality_rows)), 4),
        "dimension_semantic_quality_rate": round(sum(dimension_quality_rows) / max(1, len(dimension_quality_rows)), 4),
    }
    summary["target_thresholds"] = target
    _json_dump(root / "phase_v0_v1_packet_rows.json", packet_rows)
    _json_dump(root / "phase_v0_v1_packet_quality_rows.json", packet_quality_rows)
    _json_dump(root / "phase_v0_v1_summary.json", summary)
    (root / "phase_v0_v1_summary.md").write_text(
        "\n".join(
            [
                "# Phase V0/V1 Summary",
                "",
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
                f"- suspicious_zero_primitive_page_failures: `{summary['suspicious_zero_primitive_page_failures']}`",
                f"- suspicious_zero_primitive_packet_failures: `{summary['suspicious_zero_primitive_packet_failures']}`",
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
    result = run_phase_v0_v1_eval()
    print(json.dumps(result["summary"], indent=2))
