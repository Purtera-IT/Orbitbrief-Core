from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


@dataclass
class PageModalityDecision:
    page_index: int
    sheet_type: str
    modality: str
    confidence: float
    scores: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    diagnostics: Dict[str, float] = field(default_factory=dict)


def estimate_text_density(page_text: str, page_bbox_width: float = 1000.0, page_bbox_height: float = 1000.0) -> float:
    area = max(1.0, page_bbox_width * page_bbox_height)
    chars = len((page_text or "").strip())
    return min(1.0, chars / max(200.0, area * 0.002))


def classify_page_modality(
    *,
    page_index: int,
    sheet_type: str,
    page_text: str,
    vector_path_count: int,
    image_count: int,
    line_art_density: float,
    table_count: int,
) -> PageModalityDecision:
    text_density = estimate_text_density(page_text)
    scores = {"vector_rich": 0.0, "hybrid": 0.0, "raster_heavy": 0.0}
    reasons = []

    if vector_path_count >= 50:
        scores["vector_rich"] += 2.0
        reasons.append("high_vector_path_count")
    elif vector_path_count >= 10:
        scores["hybrid"] += 1.0
        reasons.append("moderate_vector_path_count")
    else:
        scores["raster_heavy"] += 0.5

    if image_count >= 2:
        scores["raster_heavy"] += 1.5
        reasons.append("high_image_count")
    elif image_count == 1:
        scores["hybrid"] += 0.5
        reasons.append("single_image_present")

    if line_art_density >= 0.6:
        scores["vector_rich"] += 1.0
        reasons.append("high_line_art_density")
    elif line_art_density >= 0.25:
        scores["hybrid"] += 0.75
        reasons.append("moderate_line_art_density")

    if table_count > 0 and sheet_type in {"notes_spec", "legend_symbol", "schedule_sheet"}:
        scores["hybrid"] += 0.5

    if sheet_type in {"riser_diagram", "installation_detail", "equipment_room_layout", "floorplan_overall"}:
        scores["vector_rich"] += 0.35

    if text_density > 0.4 and image_count == 0 and vector_path_count < 10:
        scores["hybrid"] += 0.4

    modality = max(scores.items(), key=lambda kv: kv[1])[0]
    confidence = min(0.99, 0.55 + 0.12 * max(scores.values()))
    return PageModalityDecision(
        page_index=page_index,
        sheet_type=sheet_type,
        modality=modality,
        confidence=confidence,
        scores=scores,
        reasons=reasons,
        diagnostics={
            "vector_path_count": float(vector_path_count),
            "image_count": float(image_count),
            "line_art_density": float(line_art_density),
            "table_count": float(table_count),
            "text_density": float(text_density),
        },
    )
