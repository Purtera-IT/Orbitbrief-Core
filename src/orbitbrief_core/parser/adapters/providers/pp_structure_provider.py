from __future__ import annotations

import io
import os
import re
import statistics
from pathlib import Path
from typing import Any

from .base import ProviderLayoutBlock, ProviderPdfHypothesis, ProviderTableRegion

_PP_ENGINE: Any | None = None
_PP_ENGINE_NAME: str = ""
_PP_ENGINE_USE_PREDICT: bool = False


def _normalize(text: Any) -> str:
    raw = str(text or "").replace("\x00", " ")
    if "<" in raw and ">" in raw:
        raw = re.sub(r"<[^>]+>", " ", raw)
    cleaned = " ".join(raw.split()).strip()
    return cleaned[:2400]


def _role(label: str, text: str) -> str:
    hint = label.lower()
    if "title" in hint or "header" in hint or "heading" in hint:
        return "heading"
    if "list" in hint:
        return "bullet"
    if "table" in hint:
        return "table"
    if text.startswith(("-", "*", "•")):
        return "bullet"
    return "paragraph"


def _pdf_source(pdf_path: Path | None, pdf_bytes: bytes | None) -> bytes | None:
    if pdf_bytes is not None:
        return pdf_bytes
    if pdf_path is not None and pdf_path.exists():
        return pdf_path.read_bytes()
    return None


def _ensure_pp_engine() -> tuple[Any, str, bool] | None:
    global _PP_ENGINE, _PP_ENGINE_NAME, _PP_ENGINE_USE_PREDICT
    try:
        try:
            from paddleocr import PPStructureV3 as _PPStructureEngine  # type: ignore

            preferred_engine_name = "PPStructureV3"
            preferred_use_predict = True
        except Exception:
            from paddleocr import PPStructure as _PPStructureEngine  # type: ignore

            preferred_engine_name = "PPStructure"
            preferred_use_predict = False
    except Exception:
        return None
    if _PP_ENGINE is None:
        try:
            _PP_ENGINE = _PPStructureEngine() if preferred_use_predict else _PPStructureEngine(show_log=False)
            _PP_ENGINE_NAME = preferred_engine_name
            _PP_ENGINE_USE_PREDICT = preferred_use_predict
        except Exception:
            return None
    return _PP_ENGINE, (_PP_ENGINE_NAME or preferred_engine_name), bool(_PP_ENGINE_USE_PREDICT)


def _extract_items_from_pp_results(
    *,
    raw_results: Any,
    use_predict: bool,
    bbox_scale: float,
) -> list[dict[str, Any]]:
    page_items: list[dict[str, Any]] = []
    if use_predict:
        for page_result in raw_results or []:
            parser_rows = getattr(page_result, "parsing_res_list", None)
            if parser_rows is None and hasattr(page_result, "get"):
                parser_rows = page_result.get("parsing_res_list", [])
            for row in parser_rows or []:
                label = str(getattr(row, "label", "") or getattr(row, "type", "") or "text")
                bbox_row = getattr(row, "bbox", None)
                content = getattr(row, "content", None)
                score = getattr(row, "score", None)
                page_items.append(
                    {
                        "type": label,
                        "bbox": bbox_row,
                        "text": content,
                        "score": score,
                        "meta": {"region_label": str(getattr(row, "region_label", "")), "bbox_scale": bbox_scale},
                    }
                )
            table_rows = getattr(page_result, "table_res_list", None)
            if table_rows is None and hasattr(page_result, "get"):
                table_rows = page_result.get("table_res_list", [])
            for table_row in table_rows or []:
                html = table_row.get("pred_html", "") if hasattr(table_row, "get") else ""
                region_id = table_row.get("table_region_id", "") if hasattr(table_row, "get") else ""
                page_items.append(
                    {
                        "type": "table",
                        "bbox": None,
                        "text": html,
                        "score": 0.8,
                        "meta": {"table_region_id": str(region_id), "bbox_scale": bbox_scale},
                    }
                )
    else:
        for item in raw_results or []:
            if not isinstance(item, dict):
                continue
            page_items.append(
                {
                    "type": str(item.get("type", "text")),
                    "bbox": item.get("bbox") or item.get("box") or item.get("region"),
                    "text": item.get("res") or item.get("text") or item.get("html") or "",
                    "score": item.get("score"),
                    "meta": {"bbox_scale": bbox_scale},
                }
            )
    return page_items


def _hypothesis_from_image(
    *,
    image_array: Any,
    page_index: int,
    source_tag: str,
    bbox_offset: tuple[float, float] = (0.0, 0.0),
) -> ProviderPdfHypothesis | None:
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    engine_info = _ensure_pp_engine()
    if engine_info is None:
        return None
    pp, engine_name, use_predict = engine_info
    if image_array is None:
        return None
    bbox_scale = 1.0
    try:
        height, width = image_array.shape[:2]
    except Exception:
        return None
    max_dim = max(height, width)
    if max_dim > 960:
        resize_ratio = 960.0 / float(max_dim)
        image_array = cv2.resize(
            image_array,
            (max(1, int(width * resize_ratio)), max(1, int(height * resize_ratio))),
            interpolation=cv2.INTER_AREA,
        )
        bbox_scale = 1.0 / resize_ratio
    try:
        raw_results = pp.predict(image_array) if use_predict else pp(image_array)
    except Exception:
        return None
    page_items = _extract_items_from_pp_results(raw_results=raw_results, use_predict=use_predict, bbox_scale=bbox_scale)
    blocks: list[ProviderLayoutBlock] = []
    tables: list[ProviderTableRegion] = []
    confidences: list[float] = []
    block_index = 0
    table_index = 0
    offset_x, offset_y = bbox_offset
    for item in page_items:
        item_type = str(item.get("type", "text"))
        text = _normalize(item.get("text") or "")
        if not text:
            continue
        region = item.get("bbox")
        bbox = None
        if isinstance(region, (list, tuple)) and len(region) >= 4:
            try:
                local_scale = float(dict(item.get("meta", {}) or {}).get("bbox_scale", 1.0))
                bbox = (
                    float(region[0]) * local_scale + offset_x,
                    float(region[1]) * local_scale + offset_y,
                    float(region[2]) * local_scale + offset_x,
                    float(region[3]) * local_scale + offset_y,
                )
            except Exception:
                bbox = None
        conf = item.get("score")
        try:
            score = max(0.0, min(1.0, float(conf)))
        except Exception:
            score = 0.78 if item_type.lower() == "table" else 0.72
        role = _role(item_type, text)
        meta = {
            "provider": "pp_structure",
            "pp_type": item_type.lower(),
            "engine": engine_name,
            "ocr_confidence": score,
            "reading_order_confidence": 0.68,
            "degraded": False,
            "source_tag": source_tag,
            **dict(item.get("meta", {}) or {}),
        }
        if role == "table":
            region_id = str(meta.get("table_region_id", "") or f"pp_structure_table:{page_index:04d}:{table_index:04d}:{source_tag}")
            tables.append(
                ProviderTableRegion(
                    region_id=region_id,
                    page_index=page_index,
                    bbox=bbox,
                    text=text,
                    confidence=score,
                    source="pp_structure",
                    metadata=meta,
                )
            )
            table_index += 1
            meta = {**meta, "table_region_id": region_id}
        blocks.append(
            ProviderLayoutBlock(
                block_id=f"pp_structure_block:{page_index:04d}:{block_index:04d}:{source_tag}",
                page_index=page_index,
                bbox=bbox,
                text=text,
                role=role,
                confidence=score,
                source="pp_structure",
                metadata=meta,
            )
        )
        confidences.append(score)
        block_index += 1
    if not blocks:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id=f"hypothesis:pp_structure:{source_tag}",
        source="pp_structure",
        page_blocks=tuple(blocks),
        table_regions=tuple(tables),
        confidence=statistics.mean(confidences) if confidences else 0.0,
        metadata={"provider": "pp_structure", "degraded": False, "source_tag": source_tag, "block_count": len(blocks), "table_count": len(tables)},
    )


def extract_pp_structure_image_hypothesis(
    *,
    image_array: Any,
    page_index: int = 0,
    source_tag: str = "crop",
    bbox_offset: tuple[float, float] = (0.0, 0.0),
) -> ProviderPdfHypothesis | None:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    return _hypothesis_from_image(
        image_array=image_array,
        page_index=page_index,
        source_tag=source_tag,
        bbox_offset=bbox_offset,
    )


def extract_pp_structure_pdf_hypothesis(*, pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> ProviderPdfHypothesis | None:
    """Layout-structure companion provider for OCR lane."""
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        import fitz  # type: ignore
        import numpy as np  # type: ignore
        import cv2  # type: ignore
    except Exception:
        return None

    raw = _pdf_source(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        doc = fitz.open(stream=raw, filetype="pdf") if raw is not None else fitz.open(pdf_path)
    except Exception:
        return None

    blocks: list[ProviderLayoutBlock] = []
    tables: list[ProviderTableRegion] = []
    confidences: list[float] = []

    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(0.95, 0.95), alpha=False)
        image_bytes = pix.tobytes("png")
        if not image_bytes:
            continue
        image_array = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            continue
        page_hypothesis = _hypothesis_from_image(
            image_array=image_array,
            page_index=page_index,
            source_tag="full_page",
        )
        if page_hypothesis is None:
            continue
        blocks.extend(page_hypothesis.page_blocks)
        tables.extend(page_hypothesis.table_regions)
        confidences.append(float(page_hypothesis.confidence))

    if not blocks:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id="hypothesis:pp_structure",
        source="pp_structure",
        page_blocks=tuple(blocks),
        table_regions=tuple(tables),
        confidence=statistics.mean(confidences) if confidences else 0.0,
        metadata={"provider": "pp_structure", "degraded": False, "block_count": len(blocks), "table_count": len(tables)},
    )
