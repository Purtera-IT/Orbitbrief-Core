from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ModalityCalibrationResult:
    modality: str
    confidence: float
    ambiguous: bool
    reasons: List[str]
    diagnostics: Dict[str, float]


def calibrate_modality_decision(
    *,
    modality: str,
    confidence: float,
    vector_path_count: int,
    image_count: int,
    line_art_density: float,
    text_density: float,
) -> ModalityCalibrationResult:
    reasons: List[str] = []
    ambiguous = False

    if modality == "vector_rich":
        if image_count >= 2 and vector_path_count < 25:
            modality = "hybrid"
            confidence = min(confidence, 0.72)
            reasons.append("downgraded_vector_rich_due_to_image_load")
        if line_art_density < 0.2 and vector_path_count < 15:
            modality = "hybrid"
            confidence = min(confidence, 0.68)
            reasons.append("downgraded_vector_rich_due_to_low_line_art")

    if modality == "raster_heavy":
        if vector_path_count >= 25 and line_art_density >= 0.3:
            modality = "hybrid"
            confidence = min(confidence, 0.70)
            reasons.append("downgraded_raster_heavy_due_to_vector_evidence")

    if abs(vector_path_count - image_count * 20) < 10 and 0.2 <= line_art_density <= 0.45:
        ambiguous = True
        reasons.append("mixed_signal_ambiguity")
        confidence = min(confidence, 0.75)

    return ModalityCalibrationResult(
        modality=modality,
        confidence=confidence,
        ambiguous=ambiguous,
        reasons=reasons,
        diagnostics={
            "vector_path_count": float(vector_path_count),
            "image_count": float(image_count),
            "line_art_density": float(line_art_density),
            "text_density": float(text_density),
        },
    )
