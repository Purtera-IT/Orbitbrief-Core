from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.symbols.training_eval import (
    bootstrap_model_predictions_from_sidecar_rows,
    build_class_balance_strategy,
    build_detector_threshold_profile,
    emit_detector_training_manifest,
    evaluate_detector_predictions,
)
from orbitbrief_core.parser.site_schematic.symbols.export import build_symbol_export_sidecar_rows


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
AP WIRELESS ACCESS POINT OUTLET
RS1 ROOM SCHEDULER
<PARSED TEXT FOR PAGE: 2 / 2>
TC100 FLOOR PLAN
AP
RS1
""".strip()


def test_training_manifest_and_bootstrap_eval(tmp_path) -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="symbol-train-eval",
            filename="symbol-train-eval.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        ),
        source_modality="site_schematic_pdf",
    )
    manifest = emit_detector_training_manifest(
        bundle=bundle,
        packet_id="wireless",
        output_dir=tmp_path,
    )
    assert manifest["detector_class_count"] >= 1
    sidecar = build_symbol_export_sidecar_rows(bundle=bundle, packet_id="wireless")
    boot = bootstrap_model_predictions_from_sidecar_rows(
        rows=sidecar,
        output_path=tmp_path / "preds.jsonl",
    )
    assert boot["prediction_count"] >= 1
    preds = [__import__("json").loads(line) for line in (tmp_path / "preds.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    report = evaluate_detector_predictions(sidecar_rows=sidecar, prediction_rows=preds)
    assert report["ground_truth_count"] >= 1
    assert report["macro_precision"] >= 0.0
    assert report["macro_recall"] >= 0.0
    assert isinstance(report["support_by_class"], dict)
    assert "top_false_positive_classes" in report
    assert "top_false_negative_classes" in report
    assert "class_weights" in boot
    assert "threshold_profile" in boot
    assert all(value >= 1.0 for value in boot["class_weights"].values())


def test_class_balance_and_threshold_profiles_are_generated() -> None:
    rows = [
        {"detector_selected_for_first_pass": True, "detector_class_id": "data_outlet", "detector_split": "train"},
        {"detector_selected_for_first_pass": True, "detector_class_id": "data_outlet", "detector_split": "val"},
        {"detector_selected_for_first_pass": True, "detector_class_id": "door_contact_marker", "detector_split": "train"},
    ]
    strategy = build_class_balance_strategy(rows, sparse_threshold=3)
    thresholds = build_detector_threshold_profile(rows)
    assert strategy["class_weights"]["door_contact_marker"] >= strategy["class_weights"]["data_outlet"]
    assert thresholds["door_contact_marker"] >= thresholds["data_outlet"]
