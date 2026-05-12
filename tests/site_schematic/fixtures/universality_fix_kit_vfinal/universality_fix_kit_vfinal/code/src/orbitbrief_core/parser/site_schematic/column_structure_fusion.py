from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


BBox = Tuple[float, float, float, float]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _bbox(value: Any) -> Optional[BBox]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except Exception:
            return None
    return None


def _center_x(b: BBox) -> float:
    return (b[0] + b[2]) / 2.0


def _width(b: BBox) -> float:
    return max(0.0, b[2] - b[0])


def _overlap_y(a: BBox, b: BBox) -> float:
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    denom = max(1e-6, min(a[3]-a[1], b[3]-b[1]))
    return inter / denom


@dataclass
class ColumnCluster:
    column_id: str
    bbox: BBox
    member_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0


def infer_holdout_columns(
    blocks: Iterable[Any],
    page_width: float,
    *,
    min_lane_width_ratio: float = 0.16,
    x_cluster_gap_ratio: float = 0.05,
) -> List[ColumnCluster]:
    recs = []
    for idx, block in enumerate(blocks):
        bbox = _bbox(_get(block, "bbox"))
        if not bbox:
            continue
        txt = (_get(block, "text", "") or "").strip()
        recs.append({
            "id": _get(block, "block_id", f"blk:{idx}"),
            "bbox": bbox,
            "x": _center_x(bbox),
            "text": txt,
        })
    if not recs or page_width <= 0:
        return []

    recs.sort(key=lambda r: r["x"])
    gap = max(18.0, page_width * x_cluster_gap_ratio)

    groups: List[List[dict]] = []
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

    lanes: List[ColumnCluster] = []
    min_w = page_width * min_lane_width_ratio
    for i, grp in enumerate(groups):
        xs0 = [r["bbox"][0] for r in grp]
        ys0 = [r["bbox"][1] for r in grp]
        xs1 = [r["bbox"][2] for r in grp]
        ys1 = [r["bbox"][3] for r in grp]
        bbox = (min(xs0), min(ys0), max(xs1), max(ys1))
        if _width(bbox) < min_w and len(grp) < 2:
            continue
        conf = min(1.0, 0.5 + 0.06 * len(grp))
        lanes.append(ColumnCluster(
            column_id=f"col:{i+1}",
            bbox=bbox,
            member_ids=[r["id"] for r in grp],
            confidence=conf,
        ))
    return lanes


def classify_note_scope_with_columns(
    note_block: Any,
    *,
    detail_regions: Iterable[Any] | None = None,
    pseudo_pages: Iterable[Any] | None = None,
    column_lanes: Iterable[ColumnCluster] | None = None,
    detail_tokens: Iterable[str] | None = None,
) -> Dict[str, Any]:
    detail_tokens = list(detail_tokens or [])
    bbox = _bbox(_get(note_block, "bbox"))
    if not bbox:
        return {"scope_class": "unresolved", "confidence": 0.0, "reasons": ["missing_bbox"]}

    # detail-local first
    for coll_name, objs in [("detail_region_id", detail_regions or []), ("pseudo_page_id", pseudo_pages or [])]:
        for obj in objs:
            ob = _bbox(_get(obj, "bbox"))
            if not ob:
                continue
            if _overlap_y(bbox, ob) >= 0.55:
                conf = 0.85 + (0.05 if detail_tokens else 0.0)
                return {
                    "scope_class": "detail_local",
                    "confidence": min(conf, 1.0),
                    "reasons": [f"{coll_name}_overlap"] + (["detail_tokens_present"] if detail_tokens else []),
                    "locality_ids": {coll_name: _get(obj, coll_name, _get(obj, "region_id", "unknown"))},
                }

    for lane in column_lanes or []:
        if _overlap_y(bbox, lane.bbox) >= 0.55:
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
