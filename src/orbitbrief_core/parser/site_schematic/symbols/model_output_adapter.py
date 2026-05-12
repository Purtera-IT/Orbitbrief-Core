from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.parser.site_schematic.models import SiteSchematicPrimitiveDetection
from orbitbrief_core.parser.site_schematic.symbols.detector_class_map import build_first_pass_detector_class_map


def _load_prediction_rows(predictions_path: Path) -> list[dict[str, Any]]:
    if not predictions_path.exists():
        return []
    if predictions_path.suffix.lower() in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        return rows
    payload = json.loads(predictions_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("predictions"), list):
        return [row for row in payload["predictions"] if isinstance(row, dict)]
    return []


def load_model_primitive_detections(
    *,
    metadata: Mapping[str, Any] | None,
    model_registry: Mapping[str, Any],
    page_count: int,
    packet_id: str,
) -> tuple[dict[int, tuple[SiteSchematicPrimitiveDetection, ...]], dict[str, Any]]:
    symbol_cfg = dict(model_registry.get("symbol_detector") or {})
    enabled = bool(symbol_cfg.get("enabled", False))
    available = bool(symbol_cfg.get("available", False))
    packet_id = packet_id or "unknown_packet"
    metadata = dict(metadata or {})
    model_rows = metadata.get("symbol_detector_predictions")
    model_path = metadata.get("symbol_detector_predictions_path") or symbol_cfg.get("predictions_path")
    explicit_predictions = isinstance(model_rows, list) or bool(model_path)
    if not enabled and not explicit_predictions:
        return ({}, {"symbol_model_adapter_used": False, "reason": "symbol_detector_disabled"})
    if not available and not model_rows and not model_path:
        return ({}, {"symbol_model_adapter_used": False, "reason": "symbol_detector_unavailable"})
    rows: list[dict[str, Any]] = []
    if isinstance(model_rows, list):
        rows = [row for row in model_rows if isinstance(row, dict)]
    elif model_path:
        rows = _load_prediction_rows(Path(str(model_path)))
    if not rows:
        return ({}, {"symbol_model_adapter_used": False, "reason": "no_model_prediction_rows"})

    detector_map = build_first_pass_detector_class_map()
    valid_detector_ids = {row["detector_class_id"] for row in detector_map["detector_classes"]}
    grouped: dict[int, list[SiteSchematicPrimitiveDetection]] = {idx: [] for idx in range(1, page_count + 1)}
    dropped = 0
    for idx, row in enumerate(rows, start=1):
        page_index = int(row.get("page_index", 0) or 0)
        detector_class_id = str(row.get("detector_class_id", "")).strip()
        if page_index <= 0 or page_index > page_count:
            dropped += 1
            continue
        if detector_class_id not in valid_detector_ids:
            dropped += 1
            continue
        bbox_value = row.get("bbox")
        bbox = None
        if isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
            try:
                bbox = tuple(float(v) for v in bbox_value)  # type: ignore[assignment]
            except Exception:
                bbox = None
        grouped[page_index].append(
            SiteSchematicPrimitiveDetection(
                detection_id=str(row.get("detection_id") or f"model_det:p{page_index}:{idx}"),
                page_index=page_index,
                primitive_family=detector_class_id,
                token_hint=str(row.get("token_hint", "")).strip(),
                bbox=bbox,
                score=float(row.get("score", 0.0) or 0.0),
                source_provider=str(row.get("source_provider") or symbol_cfg.get("provider") or "model_adapter"),
                region_id=str(row.get("region_id", "")).strip(),
                detail_region_id=str(row.get("detail_region_id", "")).strip(),
                subregion_id=str(row.get("subregion_id", "")).strip(),
                pseudo_page_id=str(row.get("pseudo_page_id", "")).strip(),
                metadata={
                    "packet_id": str(row.get("packet_id", packet_id)),
                    "candidate_id": str(row.get("candidate_id", "")).strip(),
                    "ontology_class_id": str(row.get("ontology_class_id", "")).strip(),
                    "selection_status": "selected",
                    **dict(row.get("metadata") or {}),
                },
            )
        )
    return (
        {page: tuple(values) for page, values in grouped.items() if values},
        {
            "symbol_model_adapter_used": True,
            "prediction_row_count": len(rows),
            "accepted_prediction_rows": sum(len(values) for values in grouped.values()),
            "dropped_prediction_rows": dropped,
        },
    )

