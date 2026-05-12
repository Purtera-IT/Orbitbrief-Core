from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

BBox = Tuple[float, float, float, float]


@dataclass
class VectorPrimitive:
    primitive_id: str
    primitive_kind: str
    bbox: Optional[BBox]
    page_index: int
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


def _bbox_from_points(points: List[Tuple[float, float]]) -> Optional[BBox]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def extract_vector_primitives_from_drawings(drawings: Iterable[Dict[str, Any]], *, page_index: int) -> List[VectorPrimitive]:
    """
    Starter normalizer for PyMuPDF `Page.get_drawings()`-like outputs.
    This is intentionally conservative and provenance-first.
    """
    out: List[VectorPrimitive] = []
    for d_idx, drawing in enumerate(drawings):
        items = drawing.get("items", []) or []
        for i_idx, item in enumerate(items):
            tag = item[0] if item else ""
            prim_id = f"vec:{page_index}:{d_idx}:{i_idx}"
            if tag == "l" and len(item) >= 3:
                p1, p2 = item[1], item[2]
                bbox = _bbox_from_points([tuple(p1), tuple(p2)])
                out.append(VectorPrimitive(prim_id, "line", bbox, page_index, 0.9, {"raw_tag": tag, "points": [p1, p2]}))
            elif tag == "re" and len(item) >= 2:
                rect = item[1]
                bbox = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
                out.append(VectorPrimitive(prim_id, "box", bbox, page_index, 0.9, {"raw_tag": tag}))
            elif tag == "qu" and len(item) >= 2:
                pts = [tuple(p) for p in item[1]]
                out.append(VectorPrimitive(prim_id, "polyline", _bbox_from_points(pts), page_index, 0.8, {"raw_tag": tag, "points": pts}))
            elif tag == "c":
                # curve / circle-ish fallback
                pts = []
                for part in item[1:]:
                    if isinstance(part, (list, tuple)) and len(part) == 2:
                        pts.append(tuple(part))
                out.append(VectorPrimitive(prim_id, "curve", _bbox_from_points(pts), page_index, 0.6, {"raw_tag": tag, "points": pts}))
    return out
