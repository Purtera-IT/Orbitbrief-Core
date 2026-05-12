from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import build_first_pass_detector_class_map
from orbitbrief_core.parser.site_schematic.symbols.model_output_adapter import load_model_primitive_detections


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 1>
TC100 FLOOR PLAN
CONFERENCE ROOM 101
""".strip()


def test_model_output_adapter_loads_prediction_rows_without_enabled_flag() -> None:
    detector_class_id = build_first_pass_detector_class_map()["detector_classes"][0]["detector_class_id"]
    grouped, diag = load_model_primitive_detections(
        metadata={
            "symbol_detector_predictions": [
                {
                    "page_index": 1,
                    "detector_class_id": detector_class_id,
                    "token_hint": "AP",
                    "bbox": [0.1, 0.1, 0.3, 0.3],
                    "score": 0.88,
                    "source_provider": "unit_test_model",
                }
            ]
        },
        model_registry={"symbol_detector": {"enabled": False, "available": False}},
        page_count=1,
        packet_id="unit-packet",
    )
    assert diag["symbol_model_adapter_used"] is True
    assert grouped[1]
    assert grouped[1][0].primitive_family == detector_class_id


def test_core_uses_model_output_adapter_predictions_when_supplied() -> None:
    detector_class_id = build_first_pass_detector_class_map()["detector_classes"][0]["detector_class_id"]
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="model-adapter-core",
            filename="model-adapter-core.pdf",
            mime_type="application/pdf",
            metadata={
                "full_text": SAMPLE_TEXT,
                "symbol_detector_predictions": [
                    {
                        "page_index": 1,
                        "detector_class_id": detector_class_id,
                        "token_hint": "AP",
                        "bbox": [0.1, 0.1, 0.3, 0.3],
                        "score": 0.91,
                        "source_provider": "unit_test_model",
                    }
                ],
            },
        ),
        source_modality="site_schematic_pdf",
    )
    assert bundle.symbol_instances
    assert any(row.source_mode == "unit_test_model" for row in bundle.symbol_instances)
    diag = bundle.model_registry.get("symbol_model_adapter", {})
    assert diag.get("symbol_model_adapter_used") is True
