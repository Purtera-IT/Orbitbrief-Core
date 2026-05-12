from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class VectorPrimitive:
    primitive_id: str
    primitive_kind: str
    bbox: BBox | None
    page_index: int
    confidence: float
    source_mode: str = "pdf_native"
    provider: str = "fitz"
    metadata: dict[str, Any] = field(default_factory=dict)


def _bbox_from_points(points: list[tuple[float, float]]) -> BBox | None:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def extract_vector_primitives_from_drawings(
    drawings: list[dict[str, Any]],
    *,
    page_index: int,
) -> list[VectorPrimitive]:
    out: list[VectorPrimitive] = []
    for d_idx, drawing in enumerate(drawings):
        items = drawing.get("items", []) or []
        rect = drawing.get("rect")
        rect_bbox = None
        if rect is not None:
            try:
                rect_bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
            except Exception:
                rect_bbox = None
        for i_idx, item in enumerate(items):
            tag = item[0] if item else ""
            prim_id = f"vec:{page_index}:{d_idx}:{i_idx}"
            if tag == "l" and len(item) >= 3:
                p1, p2 = item[1], item[2]
                bbox = _bbox_from_points([tuple(p1), tuple(p2)]) or rect_bbox
                out.append(
                    VectorPrimitive(
                        prim_id,
                        "line",
                        bbox,
                        page_index,
                        0.9,
                        metadata={"raw_tag": tag, "points": [p1, p2]},
                    )
                )
            elif tag == "re" and len(item) >= 2:
                rect = item[1]
                bbox = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
                out.append(VectorPrimitive(prim_id, "box", bbox, page_index, 0.9, metadata={"raw_tag": tag}))
            elif tag == "qu" and len(item) >= 2:
                pts = [tuple(p) for p in item[1]]
                out.append(
                    VectorPrimitive(
                        prim_id,
                        "polyline",
                        _bbox_from_points(pts) or rect_bbox,
                        page_index,
                        0.8,
                        metadata={"raw_tag": tag, "points": pts},
                    )
                )
            elif tag == "c":
                pts = []
                for part in item[1:]:
                    if isinstance(part, (list, tuple)) and len(part) == 2:
                        pts.append(tuple(part))
                out.append(
                    VectorPrimitive(
                        prim_id,
                        "curve",
                        _bbox_from_points(pts) or rect_bbox,
                        page_index,
                        0.6,
                        metadata={"raw_tag": tag, "points": pts},
                    )
                )
            else:
                points: list[tuple[float, float]] = []
                for part in item[1:]:
                    if isinstance(part, (list, tuple)):
                        if len(part) == 2 and all(isinstance(v, (int, float)) for v in part):
                            points.append((float(part[0]), float(part[1])))
                        elif len(part) >= 2 and isinstance(part[0], (list, tuple)):
                            for nested in part:
                                if isinstance(nested, (list, tuple)) and len(nested) == 2:
                                    points.append((float(nested[0]), float(nested[1])))
                bbox = _bbox_from_points(points) or rect_bbox
                if bbox is None:
                    continue
                out.append(
                    VectorPrimitive(
                        prim_id,
                        "polyline",
                        bbox,
                        page_index,
                        0.55,
                        metadata={"raw_tag": tag, "fallback": True},
                    )
                )
        if not items and rect_bbox is not None:
            out.append(
                VectorPrimitive(
                    f"vec:{page_index}:{d_idx}:rect_fallback",
                    "polyline",
                    rect_bbox,
                    page_index,
                    0.5,
                    metadata={"raw_tag": "rect_fallback"},
                )
            )
    return out


def extract_vector_primitives_from_vector_items(
    vector_items: list[Any],
    *,
    page_index: int,
) -> list[VectorPrimitive]:
    out: list[VectorPrimitive] = []
    for idx, row in enumerate(vector_items):
        bbox = getattr(row, "bbox", None)
        kind = str(getattr(row, "kind", "path") or "path").lower()
        primitive_kind = "polyline"
        if "line" in kind:
            primitive_kind = "line"
        elif "rect" in kind or "box" in kind:
            primitive_kind = "box"
        elif "curve" in kind or "circle" in kind or "arc" in kind:
            primitive_kind = "curve"
        out.append(
            VectorPrimitive(
                primitive_id=str(getattr(row, "vector_id", f"vec:{page_index}:obs:{idx}")),
                primitive_kind=primitive_kind,
                bbox=bbox,
                page_index=page_index,
                confidence=float(getattr(row, "confidence", 0.75) or 0.75),
                source_mode=str(getattr(row, "source_mode", "pdf_native")),
                provider=str(getattr(row, "provider", "fitz")),
                metadata=dict(getattr(row, "metadata", {}) or {}),
            )
        )
    return out
