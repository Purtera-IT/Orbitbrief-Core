from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PacketV0V1Summary:
    packet_id: str
    page_count: int
    modality_counts: dict[str, int] = field(default_factory=dict)
    ambiguous_page_count: int = 0
    primitive_count: int = 0
    validated_primitive_count: int = 0
    leader_candidate_count: int = 0
    dimension_candidate_count: int = 0
    modality_fail: bool = False
    primitive_graph_fail: bool = False


def summarize_packet_v0_v1(
    *,
    packet_id: str,
    page_modality_rows: list[dict[str, Any]],
    primitive_graph_rows: list[dict[str, Any]],
) -> PacketV0V1Summary:
    modality_counts: dict[str, int] = {}
    ambiguous_page_count = 0
    primitive_count = 0
    validated_primitive_count = 0
    leader_candidate_count = 0
    dimension_candidate_count = 0
    for row in page_modality_rows:
        modality = str(row.get("modality", "unknown"))
        modality_counts[modality] = modality_counts.get(modality, 0) + 1
        if bool(row.get("ambiguous", False)):
            ambiguous_page_count += 1
    for row in primitive_graph_rows:
        primitive_count += int(row.get("primitive_count", 0) or 0)
        validated_primitive_count += int(row.get("validated_primitive_count", row.get("primitive_count", 0)) or 0)
        leader_candidate_count += int(row.get("leader_candidate_count", 0) or 0)
        dimension_candidate_count += int(row.get("dimension_candidate_count", 0) or 0)
    has_suspicious_graph_row = any(bool(row.get("suspicious_zero_primitive", False)) for row in primitive_graph_rows)
    return PacketV0V1Summary(
        packet_id=packet_id,
        page_count=len(page_modality_rows),
        modality_counts=modality_counts,
        ambiguous_page_count=ambiguous_page_count,
        primitive_count=primitive_count,
        validated_primitive_count=validated_primitive_count,
        leader_candidate_count=leader_candidate_count,
        dimension_candidate_count=dimension_candidate_count,
        modality_fail=(len(page_modality_rows) == 0),
        primitive_graph_fail=(
            primitive_count == 0
            and any(str(row.get("modality", "")) == "vector_rich" for row in page_modality_rows)
        ) or has_suspicious_graph_row,
    )
