from __future__ import annotations

from dataclasses import is_dataclass, replace
from typing import Any

BBox = tuple[float, float, float, float]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _updated_obj(obj: Any, *, bbox: BBox | None = None, metadata_patch: dict[str, Any] | None = None) -> Any:
    if isinstance(obj, dict):
        if bbox is not None:
            obj["bbox"] = bbox
        if metadata_patch:
            current = dict(obj.get("metadata") or {})
            current.update(metadata_patch)
            obj["metadata"] = current
        return obj
    if is_dataclass(obj):
        updates: dict[str, Any] = {}
        if bbox is not None:
            updates["bbox"] = bbox
        if metadata_patch:
            current = dict(_get(obj, "metadata", {}) or {})
            current.update(metadata_patch)
            updates["metadata"] = current
        if updates:
            return replace(obj, **updates)
    return obj


def _bbox(value: Any) -> BBox | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
        except Exception:
            return None
    return None


def _union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def complete_region_bbox_from_children(region: Any, children: list[Any], table_anchors: list[Any] | tuple[Any, ...] | None = None) -> tuple[Any, bool]:
    if _bbox(_get(region, "bbox")) is not None:
        return region, False
    boxes: list[BBox] = []
    for child in children:
        cb = _bbox(_get(child, "bbox"))
        if cb is not None:
            boxes.append(cb)
    for table in (table_anchors or []):
        tb = _bbox(_get(table, "bbox"))
        if tb is not None:
            boxes.append(tb)
    union_box = _union(boxes)
    if union_box is None:
        return region, False
    updated = _updated_obj(
        region,
        bbox=union_box,
        metadata_patch={"bbox_completed_from_children": True},
    )
    return updated, True


def ensure_locality_provenance(
    obj: Any,
    *,
    parent_region_id: str = "",
    detail_region_id: str = "",
    subregion_id: str = "",
    pseudo_page_id: str = "",
) -> tuple[Any, bool]:
    meta = dict(_get(obj, "metadata", {}) or {})
    locality_ids = dict(meta.get("locality_ids", {}) or {})
    changed = False
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
    if not locality_ids.get("region_id"):
        locality_ids["region_id"] = parent_region_id or "page_global"
        changed = True
    if not changed:
        return obj, False
    updated = _updated_obj(
        obj,
        metadata_patch={"locality_ids": locality_ids},
    )
    return updated, True
