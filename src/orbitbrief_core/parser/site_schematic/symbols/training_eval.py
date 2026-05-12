from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle
from orbitbrief_core.parser.site_schematic.symbols.export import build_symbol_export_sidecar_rows, export_symbol_candidate_crops
from orbitbrief_core.parser.site_schematic.symbols.profile_routing import (
    get_detector_profile,
    is_class_suppressed,
    profile_threshold_delta,
    select_profile_for_candidate_row,
)

_LOW_VOLTAGE_PRIORITY_CLASSES = {
    "data_outlet",
    "door_contact_marker",
    "riser_endpoint",
    "telecomm_jack_tag",
    "equipment_rack_front",
    "j_hook_pathway_symbol",
    "wireless_node_wall_outlet",
    "zigbee_node_ceiling_outlet",
}


def summarize_detector_dataset_rows(rows: list[dict[str, Any]], *, sparse_threshold: int = 5) -> dict[str, Any]:
    filtered = [row for row in rows if row.get("detector_selected_for_first_pass") and row.get("detector_class_id")]
    by_class = Counter(str(row["detector_class_id"]) for row in filtered)
    by_split = Counter(str(row.get("detector_split", "train")) for row in filtered)
    by_class_split: dict[str, Counter[str]] = defaultdict(Counter)
    for row in filtered:
        by_class_split[str(row["detector_class_id"])][str(row.get("detector_split", "train"))] += 1
    sparse_classes = sorted([key for key, value in by_class.items() if value < sparse_threshold])
    return {
        "detector_row_count": len(filtered),
        "detector_class_count": len(by_class),
        "split_counts": dict(by_split),
        "per_class_counts": dict(sorted(by_class.items(), key=lambda item: (-item[1], item[0]))),
        "per_class_split_counts": {key: dict(value) for key, value in sorted(by_class_split.items())},
        "sparse_threshold": sparse_threshold,
        "sparse_classes": sparse_classes,
    }


def build_class_balance_strategy(rows: list[dict[str, Any]], *, sparse_threshold: int = 5) -> dict[str, Any]:
    summary = summarize_detector_dataset_rows(rows, sparse_threshold=sparse_threshold)
    counts = dict(summary["per_class_counts"])
    if not counts:
        return {"class_weights": {}, "sparse_strategy": {}, "sparse_threshold": sparse_threshold}
    max_count = max(counts.values())
    class_weights: dict[str, float] = {}
    sparse_strategy: dict[str, str] = {}
    for class_id, value in counts.items():
        ratio = max_count / max(1, value)
        class_weights[class_id] = round(min(4.0, max(1.0, ratio ** 0.5)), 4)
        if value < sparse_threshold:
            sparse_strategy[class_id] = "keep_separate_upweight_and_conservative_threshold"
        elif value < (sparse_threshold * 2):
            sparse_strategy[class_id] = "keep_separate_moderate_upweight"
        else:
            sparse_strategy[class_id] = "standard_weight"
    return {
        "class_weights": class_weights,
        "sparse_strategy": sparse_strategy,
        "sparse_threshold": sparse_threshold,
    }


def build_detector_threshold_profile(
    rows: list[dict[str, Any]],
    *,
    default_threshold: float = 0.58,
) -> dict[str, float]:
    summary = summarize_detector_dataset_rows(rows)
    counts = dict(summary["per_class_counts"])
    thresholds: dict[str, float] = {}
    for class_id, value in counts.items():
        threshold = default_threshold
        if class_id in _LOW_VOLTAGE_PRIORITY_CLASSES:
            threshold += 0.06
        if value <= 2:
            threshold += 0.06
        elif value <= 4:
            threshold += 0.03
        thresholds[class_id] = round(min(0.82, max(0.45, threshold)), 4)
    return thresholds


def emit_detector_training_manifest(
    *,
    bundle: SiteSchematicBundle,
    packet_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_symbol_export_sidecar_rows(bundle=bundle, packet_id=packet_id)
    summary = summarize_detector_dataset_rows(rows)
    manifest = {
        "packet_id": packet_id,
        "manifest_version": "2026-04-09.detector_training_manifest_v1",
        "summary": summary,
        "rows": rows,
    }
    path = output_dir / "detector_training_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    for split in ("train", "val", "test"):
        split_rows = [row for row in rows if str(row.get("detector_split", "train")) == split and row.get("detector_class_id")]
        (output_dir / f"detector_{split}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in split_rows),
            encoding="utf-8",
        )
    return {
        "manifest_path": str(path),
        "split_files": {split: str(output_dir / f"detector_{split}.jsonl") for split in ("train", "val", "test")},
        **summary,
    }


def bootstrap_model_predictions_from_sidecar_rows(
    *,
    rows: list[dict[str, Any]],
    output_path: Path,
    provider: str = "bootstrap_symbol_model_v1",
) -> dict[str, Any]:
    class_balance = build_class_balance_strategy(rows)
    class_weights = dict(class_balance.get("class_weights", {}))
    threshold_profile = build_detector_threshold_profile(rows)
    predictions: list[dict[str, Any]] = []
    dropped_for_threshold = 0
    dropped_for_profile_suppression = 0
    for row in rows:
        detector_class_id = str(row.get("detector_class_id") or "")
        if not detector_class_id or not row.get("detector_selected_for_first_pass"):
            continue
        profile_id, profile_reasons = select_profile_for_candidate_row(row)
        profile = get_detector_profile(profile_id)
        favored_classes = set(profile.get("favored_classes", set()))
        suppressed_classes = set(profile.get("suppressed_classes", set()))
        if is_class_suppressed(profile_id, detector_class_id):
            dropped_for_profile_suppression += 1
            continue
        base_score = 0.79 if bool(row.get("vocabulary_focus_matched", False)) else 0.72
        class_weight = float(class_weights.get(detector_class_id, 1.0))
        score = min(0.95, base_score + min(0.08, (class_weight - 1.0) * 0.04))
        if detector_class_id in favored_classes:
            score = min(0.95, score + 0.03)
        class_threshold = float(threshold_profile.get(detector_class_id, 0.58))
        class_threshold = max(0.45, min(0.9, class_threshold + profile_threshold_delta(profile_id, detector_class_id)))
        if score < class_threshold:
            dropped_for_threshold += 1
            continue
        predictions.append(
            {
                "detection_id": f"pred:{row['candidate_id']}",
                "packet_id": row.get("packet_id", ""),
                "page_index": int(row.get("page_index", 0) or 0),
                "candidate_id": row.get("candidate_id", ""),
                "detector_class_id": detector_class_id,
                "ontology_class_id": row.get("ontology_primary_class_id", ""),
                "token_hint": _token_hint_for_detector(detector_class_id),
                "bbox": row.get("bbox"),
                "score": score,
                "source_provider": provider,
                "region_id": row.get("region_id", ""),
                "detail_region_id": row.get("detail_region_id", ""),
                "subregion_id": row.get("subregion_id", ""),
                "pseudo_page_id": row.get("pseudo_page_id", ""),
                "metadata": {
                    "bootstrap": True,
                    "split": row.get("detector_split", "train"),
                    "class_weight": class_weight,
                    "class_threshold": class_threshold,
                    "detector_profile_id": profile_id,
                    "detector_profile_reasons": list(profile_reasons),
                    "detector_profile_favored_classes": sorted(favored_classes),
                    "detector_profile_suppressed_classes": sorted(suppressed_classes),
                },
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in predictions), encoding="utf-8")
    return {
        "prediction_count": len(predictions),
        "dropped_for_threshold": dropped_for_threshold,
        "dropped_for_profile_suppression": dropped_for_profile_suppression,
        "predictions_path": str(output_path),
        "provider": provider,
        "class_weights": class_weights,
        "threshold_profile": threshold_profile,
    }


def _token_hint_for_detector(detector_class_id: str) -> str:
    lookup = {
        "wireless_access_point_marker": "AP",
        "wall_mounted_ap_marker": "WM",
        "ceiling_mounted_ap_marker": "CM",
        "projector_av_outlet_marker": "AV",
        "room_scheduler_outlet_marker": "RS1",
        "token_ap": "AP",
        "token_wm_ap": "WM",
        "token_cm": "CM",
        "token_av": "AV",
        "token_cip": "CIP",
        "pull_box_marker": "PP",
        "patch_panel_row": "PP",
        "data_outlet": "DATA",
        "door_contact_marker": "DC",
        "riser_endpoint": "RIS",
        "telecomm_jack_tag": "JACK",
        "j_hook_pathway_symbol": "J-HOOK",
        "equipment_rack_front": "RACK",
        "wireless_node_wall_outlet": "WN",
        "zigbee_node_ceiling_outlet": "ZN",
        "ladder_rack_cable_runway": "LADDER",
    }
    return lookup.get(detector_class_id, detector_class_id[:8].upper())


def evaluate_detector_predictions(
    *,
    sidecar_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    gt = {
        str(row["candidate_id"]): str(row["detector_class_id"])
        for row in sidecar_rows
        if row.get("detector_selected_for_first_pass") and row.get("detector_class_id")
    }
    pred_by_candidate: dict[str, tuple[str, float]] = {}
    for row in prediction_rows:
        candidate_id = str(row.get("candidate_id", ""))
        detector_class_id = str(row.get("detector_class_id", ""))
        score = float(row.get("score", 0.0) or 0.0)
        if not candidate_id or not detector_class_id:
            continue
        existing = pred_by_candidate.get(candidate_id)
        if existing is None or score > existing[1]:
            pred_by_candidate[candidate_id] = (detector_class_id, score)

    tp = Counter()
    fp = Counter()
    fn = Counter()
    for candidate_id, gt_class in gt.items():
        pred = pred_by_candidate.get(candidate_id)
        if pred is None:
            fn[gt_class] += 1
            continue
        pred_class = pred[0]
        if pred_class == gt_class:
            tp[gt_class] += 1
        else:
            fp[pred_class] += 1
            fn[gt_class] += 1
    for candidate_id, (pred_class, _) in pred_by_candidate.items():
        if candidate_id not in gt:
            fp[pred_class] += 1

    classes = sorted(set(tp.keys()) | set(fp.keys()) | set(fn.keys()))
    per_class = {}
    for class_id in classes:
        precision = tp[class_id] / max(1, tp[class_id] + fp[class_id])
        recall = tp[class_id] / max(1, tp[class_id] + fn[class_id])
        per_class[class_id] = {
            "tp": int(tp[class_id]),
            "fp": int(fp[class_id]),
            "fn": int(fn[class_id]),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }
    macro_precision = sum(row["precision"] for row in per_class.values()) / max(1, len(per_class))
    macro_recall = sum(row["recall"] for row in per_class.values()) / max(1, len(per_class))
    support = {class_id: int(tp[class_id] + fn[class_id]) for class_id in classes}
    return {
        "ground_truth_count": len(gt),
        "prediction_count": len(pred_by_candidate),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "support_by_class": support,
        "per_class": per_class,
        "top_false_positive_classes": [row[0] for row in fp.most_common(10)],
        "top_false_negative_classes": [row[0] for row in fn.most_common(10)],
    }


def export_and_manifest_for_training(
    *,
    bundle: SiteSchematicBundle,
    packet_id: str,
    pdf_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    export = export_symbol_candidate_crops(bundle=bundle, pdf_path=pdf_path, output_dir=output_dir / "crops", packet_id=packet_id)
    rows = [json.loads(line) for line in Path(export["metadata_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = emit_detector_training_manifest(bundle=bundle, packet_id=packet_id, output_dir=output_dir)
    bootstrap = bootstrap_model_predictions_from_sidecar_rows(rows=rows, output_path=output_dir / "bootstrap_model_predictions.jsonl")
    eval_report = evaluate_detector_predictions(sidecar_rows=rows, prediction_rows=[json.loads(line) for line in Path(bootstrap["predictions_path"]).read_text(encoding="utf-8").splitlines() if line.strip()])
    return {"export": export, "manifest": manifest, "bootstrap_predictions": bootstrap, "evaluation": eval_report}

