from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re
from typing import Any, Mapping

from orbitbrief_core.parser.shared.types import EvidenceSpan


def same_sheet(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    return tuple(left.section_path[:2]) == tuple(right.section_path[:2]) and len(left.section_path) >= 2 and len(right.section_path) >= 2


def same_zone(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    left_kind = str(left.metadata.get("kind", "")).lower()
    right_kind = str(right.metadata.get("kind", "")).lower()
    if left_kind not in {"room_label", "equipment_label"} or right_kind not in {"room_label", "equipment_label"}:
        return False
    return tuple(left.section_path) == tuple(right.section_path)


def is_note_like(span: EvidenceSpan) -> bool:
    return str(span.metadata.get("kind", "")).lower() in {"note_block", "callout"}


def is_callout(span: EvidenceSpan) -> bool:
    return str(span.metadata.get("kind", "")).lower() == "callout"


def is_component(span: EvidenceSpan) -> bool:
    return str(span.metadata.get("kind", "")).lower() == "equipment_label"


def is_zone_like(span: EvidenceSpan) -> bool:
    return str(span.metadata.get("kind", "")).lower() in {"room_label"}


def is_region_span(span: EvidenceSpan) -> bool:
    return str(span.metadata.get("kind", "")).lower() in {"visual_region", "note_block", "room_label", "equipment_label", "dimension_text", "title_block_field"}


def near(left: EvidenceSpan, right: EvidenceSpan, *, max_rank_delta: int = 4) -> bool:
    if left.chronology_rank is None or right.chronology_rank is None:
        return False
    return abs(left.chronology_rank - right.chronology_rank) <= max_rank_delta


def possible_topology_neighbor(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    left_kind = str(left.metadata.get("kind", "")).lower()
    right_kind = str(right.metadata.get("kind", "")).lower()
    return left_kind == "equipment_label" and right_kind == "equipment_label" and near(left, right, max_rank_delta=6)


def normalized_tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def lexical_overlap(left: str, right: str) -> float:
    a = normalized_tokens(left)
    b = normalized_tokens(right)
    if not a or not b:
        return 0.0
    denom = max(len(a | b), 1)
    return len(a & b) / denom


def normalized_label_match(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    return bool(left.normalized_text and right.normalized_text and left.normalized_text == right.normalized_text)


def component_prefix_match(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    if not is_component(left) or not is_component(right):
        return False
    left_prefix = re.split(r"[-_# ]+", left.normalized_text.strip())[0]
    right_prefix = re.split(r"[-_# ]+", right.normalized_text.strip())[0]
    return bool(left_prefix and right_prefix and left_prefix == right_prefix)


def room_or_closet_pattern_match(span: EvidenceSpan) -> bool:
    return bool(re.search(r"\b(room|closet|mdf|idf)\b", span.normalized_text.lower()))


def revision_marker_match(span: EvidenceSpan) -> bool:
    if str(span.metadata.get("kind", "")).lower() == "revision_block":
        return True
    return bool(re.search(r"\brev(?:ision)?\s*[a-z0-9]+\b", span.normalized_text.lower()))


def bbox_distance(left: EvidenceSpan, right: EvidenceSpan) -> float | None:
    if left.bbox is None or right.bbox is None:
        return None
    lx = (left.bbox.x0 + left.bbox.x1) / 2.0
    ly = (left.bbox.y0 + left.bbox.y1) / 2.0
    rx = (right.bbox.x0 + right.bbox.x1) / 2.0
    ry = (right.bbox.y0 + right.bbox.y1) / 2.0
    return float(sqrt(((lx - rx) ** 2) + ((ly - ry) ** 2)))


def overlap_ratio(left: EvidenceSpan, right: EvidenceSpan) -> float:
    if left.bbox is None or right.bbox is None:
        return 0.0
    x0 = max(left.bbox.x0, right.bbox.x0)
    y0 = max(left.bbox.y0, right.bbox.y0)
    x1 = min(left.bbox.x1, right.bbox.x1)
    y1 = min(left.bbox.y1, right.bbox.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    left_area = (left.bbox.x1 - left.bbox.x0) * (left.bbox.y1 - left.bbox.y0)
    right_area = (right.bbox.x1 - right.bbox.x0) * (right.bbox.y1 - right.bbox.y0)
    union = max(left_area + right_area - inter, 1e-9)
    return float(inter / union)


def containment(left: EvidenceSpan, right: EvidenceSpan) -> bool:
    if left.bbox is None or right.bbox is None:
        return False
    return (
        left.bbox.x0 <= right.bbox.x0
        and left.bbox.y0 <= right.bbox.y0
        and left.bbox.x1 >= right.bbox.x1
        and left.bbox.y1 >= right.bbox.y1
    )


def alignment_score(left: EvidenceSpan, right: EvidenceSpan) -> float:
    if left.bbox is None or right.bbox is None:
        return 0.0
    left_cx = (left.bbox.x0 + left.bbox.x1) / 2.0
    right_cx = (right.bbox.x0 + right.bbox.x1) / 2.0
    left_cy = (left.bbox.y0 + left.bbox.y1) / 2.0
    right_cy = (right.bbox.y0 + right.bbox.y1) / 2.0
    dx = abs(left_cx - right_cx)
    dy = abs(left_cy - right_cy)
    return 1.0 if dx <= 0.05 or dy <= 0.05 else max(0.0, 1.0 - min(dx + dy, 1.0))


def border_proximity(span: EvidenceSpan) -> float:
    if span.bbox is None:
        return 0.0
    nearest = min(span.bbox.x0, span.bbox.y0, max(0.0, 1.0 - span.bbox.x1), max(0.0, 1.0 - span.bbox.y1))
    return max(0.0, min(1.0, 1.0 - nearest))


def title_block_proximity(span: EvidenceSpan) -> float:
    kind = str(span.metadata.get("kind", "")).lower()
    if kind in {"title_block_field", "sheet_ref"}:
        return 1.0
    return border_proximity(span) if kind == "visual_region" else 0.0


def ocr_confidence_compatibility(left: EvidenceSpan, right: EvidenceSpan) -> float:
    return max(0.0, 1.0 - abs(float(left.authority_score) - float(right.authority_score)))


def region_quality(span: EvidenceSpan) -> float:
    if str(span.metadata.get("cad_noise_downgraded", False)).lower() == "true":
        return max(0.0, float(span.authority_score) * 0.5)
    return float(span.authority_score)


def review_risk_score(span: EvidenceSpan) -> float:
    if span.review_flag_ids:
        return min(1.0, 0.4 + (0.2 * len(span.review_flag_ids)))
    if bool(span.metadata.get("cad_noise_downgraded")):
        return 0.75
    return 0.05


def same_cluster(span_id_a: str, span_id_b: str, clusters: list[dict[str, Any]], *, key: str = "items") -> bool:
    for cluster in clusters:
        ids: set[str] = set()
        values = cluster.get(key, [])
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, dict):
                value = entry.get("span_id") or entry.get("zone_span_id") or entry.get("equipment_span_id")
                if isinstance(value, str):
                    ids.add(value)
        if span_id_a in ids and span_id_b in ids:
            return True
    return False


@dataclass(frozen=True, slots=True)
class CadPairSignals:
    same_sheet: bool
    same_zone: bool
    near: bool
    overlaps: bool
    inside_region: bool
    lexical_overlap: float
    normalized_label_match: bool
    component_prefix_match: bool
    room_or_closet_pattern_match: bool
    revision_marker_match: bool
    bbox_distance: float | None
    overlap_ratio: float
    containment: bool
    alignment_score: float
    border_proximity_left: float
    border_proximity_right: float
    title_block_proximity_left: float
    title_block_proximity_right: float
    ocr_confidence_compatibility: float
    region_quality_left: float
    region_quality_right: float
    review_risk_left: float
    review_risk_right: float
    same_note_cluster: bool
    same_revision_cluster: bool
    same_title_block_bundle: bool


def pair_signals(
    left: EvidenceSpan,
    right: EvidenceSpan,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CadPairSignals:
    payload = dict(metadata or {})
    note_clusters = payload.get("note_clusters", [])
    revision_bundle = payload.get("revision_bundle", [])
    title_bundle = payload.get("title_block_bundle", [])
    same_note = bool(isinstance(note_clusters, list) and same_cluster(left.span_id, right.span_id, note_clusters, key="items"))
    same_revision = bool(isinstance(revision_bundle, list) and same_cluster(left.span_id, right.span_id, revision_bundle, key="entries"))
    same_title = bool(isinstance(title_bundle, list) and same_cluster(left.span_id, right.span_id, title_bundle, key="fields"))
    ov_ratio = overlap_ratio(left, right)
    contain = containment(left, right) or containment(right, left)
    return CadPairSignals(
        same_sheet=same_sheet(left, right),
        same_zone=same_zone(left, right),
        near=near(left, right, max_rank_delta=4),
        overlaps=ov_ratio >= 0.15,
        inside_region=contain,
        lexical_overlap=lexical_overlap(left.normalized_text, right.normalized_text),
        normalized_label_match=normalized_label_match(left, right),
        component_prefix_match=component_prefix_match(left, right),
        room_or_closet_pattern_match=room_or_closet_pattern_match(left) or room_or_closet_pattern_match(right),
        revision_marker_match=revision_marker_match(left) or revision_marker_match(right),
        bbox_distance=bbox_distance(left, right),
        overlap_ratio=ov_ratio,
        containment=contain,
        alignment_score=alignment_score(left, right),
        border_proximity_left=border_proximity(left),
        border_proximity_right=border_proximity(right),
        title_block_proximity_left=title_block_proximity(left),
        title_block_proximity_right=title_block_proximity(right),
        ocr_confidence_compatibility=ocr_confidence_compatibility(left, right),
        region_quality_left=region_quality(left),
        region_quality_right=region_quality(right),
        review_risk_left=review_risk_score(left),
        review_risk_right=review_risk_score(right),
        same_note_cluster=same_note,
        same_revision_cluster=same_revision,
        same_title_block_bundle=same_title,
    )

