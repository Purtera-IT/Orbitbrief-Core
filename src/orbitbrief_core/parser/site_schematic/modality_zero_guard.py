from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SuspiciousZeroPrimitiveResult:
    suspicious: bool
    reasons: tuple[str, ...]
    severity: str


def detect_suspicious_zero_primitive_page(
    *,
    modality: str,
    vector_path_count: int,
    image_count: int,
    line_art_density: float,
    primitive_count: int,
    validated_primitive_count: int,
) -> SuspiciousZeroPrimitiveResult:
    reasons: list[str] = []
    suspicious = False
    severity = "none"
    high_vector_evidence = vector_path_count >= 25 or line_art_density >= 0.35
    if modality == "vector_rich" and validated_primitive_count == 0:
        suspicious = True
        severity = "high"
        reasons.append("vector_rich_zero_validated_primitives")
    elif modality == "hybrid" and high_vector_evidence and validated_primitive_count == 0:
        suspicious = True
        severity = "medium"
        reasons.append("hybrid_high_vector_evidence_zero_validated_primitives")
    if primitive_count == 0 and high_vector_evidence and image_count == 0:
        suspicious = True
        if severity == "none":
            severity = "high"
        reasons.append("raw_zero_primitives_with_vector_evidence")
    return SuspiciousZeroPrimitiveResult(
        suspicious=suspicious,
        reasons=tuple(reasons),
        severity=severity,
    )
