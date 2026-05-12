from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BBox = tuple[float, float, float, float]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _bbox(value: Any) -> BBox | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except Exception:
            return None
    return None


def _center_x(box: BBox) -> float:
    return (box[0] + box[2]) / 2.0


def _width(box: BBox) -> float:
    return max(0.0, box[2] - box[0])


def _overlap_y(a: BBox, b: BBox) -> float:
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    denom = max(1e-6, min(a[3] - a[1], b[3] - b[1]))
    return inter / denom


@dataclass(slots=True)
class ColumnCluster:
    column_id: str
    bbox: BBox
    member_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0


def infer_holdout_columns(
    blocks: list[Any] | tuple[Any, ...],
    page_width: float,
    *,
    min_lane_width_ratio: float = 0.16,
    x_cluster_gap_ratio: float = 0.05,
) -> list[ColumnCluster]:
    recs = []
    for idx, block in enumerate(blocks):
        box = _bbox(_get(block, "bbox"))
        if not box:
            continue
        recs.append(
            {
                "id": _get(block, "block_id", f"blk:{idx}"),
                "bbox": box,
                "x": _center_x(box),
            }
        )
    if not recs or page_width <= 0:
        return []

    recs.sort(key=lambda row: row["x"])
    gap = max(18.0, page_width * x_cluster_gap_ratio)
    groups: list[list[dict[str, Any]]] = []
    for rec in recs:
        if not groups:
            groups.append([rec])
            continue
        prev = groups[-1]
        mean_x = sum(r["x"] for r in prev) / len(prev)
        if abs(rec["x"] - mean_x) <= gap * 2.0:
            prev.append(rec)
        else:
            groups.append([rec])

    lanes: list[ColumnCluster] = []
    min_w = page_width * min_lane_width_ratio
    for idx, group in enumerate(groups):
        xs0 = [r["bbox"][0] for r in group]
        ys0 = [r["bbox"][1] for r in group]
        xs1 = [r["bbox"][2] for r in group]
        ys1 = [r["bbox"][3] for r in group]
        box = (min(xs0), min(ys0), max(xs1), max(ys1))
        if _width(box) < min_w and len(group) < 2:
            continue
        conf = min(1.0, 0.5 + 0.06 * len(group))
        lanes.append(
            ColumnCluster(
                column_id=f"col:{idx + 1}",
                bbox=box,
                member_ids=[r["id"] for r in group],
                confidence=conf,
            )
        )
    return lanes


def classify_note_scope_with_columns(
    note_block: Any,
    *,
    detail_regions: list[Any] | tuple[Any, ...] | None = None,
    pseudo_pages: list[Any] | tuple[Any, ...] | None = None,
    column_lanes: list[ColumnCluster] | tuple[ColumnCluster, ...] | None = None,
    detail_tokens: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    detail_tokens = list(detail_tokens or [])
    box = _bbox(_get(note_block, "bbox"))
    if not box:
        return {"scope_class": "unresolved", "confidence": 0.0, "reasons": ["missing_bbox"]}

    for coll_name, objs in [("detail_region_id", detail_regions or []), ("pseudo_page_id", pseudo_pages or [])]:
        for obj in objs:
            obj_box = _bbox(_get(obj, "bbox"))
            if not obj_box:
                continue
            if _overlap_y(box, obj_box) >= 0.55:
                conf = 0.85 + (0.05 if detail_tokens else 0.0)
                return {
                    "scope_class": "detail_local",
                    "confidence": min(conf, 1.0),
                    "reasons": [f"{coll_name}_overlap"] + (["detail_tokens_present"] if detail_tokens else []),
                    "locality_ids": {coll_name: _get(obj, coll_name, _get(obj, "region_id", "unknown"))},
                }

    for lane in column_lanes or []:
        if _overlap_y(box, lane.bbox) >= 0.55:
            conf = 0.72 + (0.04 if detail_tokens else 0.0)
            return {
                "scope_class": "column_local",
                "confidence": min(conf, 1.0),
                "reasons": ["column_overlap"] + (["detail_tokens_present"] if detail_tokens else []),
                "locality_ids": {"column_id": lane.column_id},
            }

    return {
        "scope_class": "page_global",
        "confidence": 0.6,
        "reasons": ["global_fallback"],
        "locality_ids": {},
    }
