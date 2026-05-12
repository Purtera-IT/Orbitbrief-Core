from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

BBox = Tuple[float, float, float, float]


def _get(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _set(obj: Any, name: str, value):
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def _bbox(value: Any) -> Optional[BBox]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except Exception:
            return None
    return None


def _union(boxes: Iterable[BBox]) -> Optional[BBox]:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def complete_region_bbox_from_children(region: Any, children: Iterable[Any], table_anchors: Iterable[Any] | None = None) -> bool:
    if _bbox(_get(region, "bbox")) is not None:
        return False
    boxes = []
    for child in children:
        cb = _bbox(_get(child, "bbox"))
        if cb:
            boxes.append(cb)
    for tab in (table_anchors or []):
        tb = _bbox(_get(tab, "bbox"))
        if tb:
            boxes.append(tb)
    ub = _union(boxes)
    if ub is None:
        return False
    _set(region, "bbox", ub)
    meta = _get(region, "metadata", {}) or {}
    meta["bbox_completed_from_children"] = True
    _set(region, "metadata", meta)
    return True


def ensure_locality_provenance(obj: Any, *, parent_region_id: str = "", detail_region_id: str = "", subregion_id: str = "", pseudo_page_id: str = "") -> bool:
    changed = False
    meta = _get(obj, "metadata", {}) or {}
    locality_ids = meta.get("locality_ids", {}) or {}
    if parent_region_id and not locality_ids.get("region_id"):
        locality_ids["region_id"] = parent_region_id
        changed = True
    if detail_region_id and not locality_ids.get("detail_region_id"):
        locality_ids["detail_region_id"] = detail_region_id
        changed = True
    if subregion_id and not locality_ids.get("subregion_id"):
        locality_ids["subregion_id"] = subregion_id
        changed = True
    if pseudo_page_id and not locality_ids.get("pseudo_page_id"):
        locality_ids["pseudo_page_id"] = pseudo_page_id
        changed = True
    if changed:
        meta["locality_ids"] = locality_ids
        _set(obj, "metadata", meta)
    return changed
