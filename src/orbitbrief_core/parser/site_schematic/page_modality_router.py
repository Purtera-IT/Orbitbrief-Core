from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PageModalityDecision:
    page_index: int
    sheet_type: str
    modality: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    diagnostics: dict[str, float] = field(default_factory=dict)


def estimate_text_density(
    page_text: str,
    *,
    page_bbox_width: float = 1000.0,
    page_bbox_height: float = 1000.0,
) -> float:
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
    reasons: list[str] = []

    if vector_path_count >= 80:
        scores["vector_rich"] += 2.5
        reasons.append("high_vector_path_count")
    elif vector_path_count >= 24:
        scores["vector_rich"] += 1.2
        scores["hybrid"] += 0.8
        reasons.append("moderate_vector_path_count")
    elif vector_path_count >= 8:
        scores["hybrid"] += 0.8
        reasons.append("light_vector_path_count")
    else:
        scores["raster_heavy"] += 0.6

    if image_count >= 3 and vector_path_count < 12:
        scores["raster_heavy"] += 2.0
        reasons.append("dominant_images")
    elif image_count >= 1:
        scores["hybrid"] += 0.6
        reasons.append("has_images")

    if line_art_density >= 0.7:
        scores["vector_rich"] += 1.0
        reasons.append("high_line_art_density")
    elif line_art_density >= 0.3:
        scores["hybrid"] += 0.7
        reasons.append("moderate_line_art_density")

    if table_count > 0 and sheet_type in {"notes_spec", "legend_symbol", "schedule_sheet"}:
        scores["hybrid"] += 0.6
        reasons.append("table_driven_sheet")

    if sheet_type in {"riser_diagram", "installation_detail", "equipment_room_layout", "floorplan_overall", "floorplan_detail"}:
        scores["vector_rich"] += 0.35
        reasons.append("vector_favor_sheet_type")

    if text_density > 0.45 and vector_path_count < 10 and image_count == 0:
        scores["hybrid"] += 0.35
        reasons.append("text_dense_no_image")

    modality = max(scores.items(), key=lambda kv: kv[1])[0]
    confidence = min(0.99, 0.55 + 0.12 * max(scores.values()))
    return PageModalityDecision(
        page_index=page_index,
        sheet_type=sheet_type or "unknown",
        modality=modality,
        confidence=confidence,
        scores=scores,
        reasons=tuple(reasons),
        diagnostics={
            "vector_path_count": float(vector_path_count),
            "image_count": float(image_count),
            "line_art_density": float(line_art_density),
            "table_count": float(table_count),
            "text_density": float(text_density),
        },
    )
