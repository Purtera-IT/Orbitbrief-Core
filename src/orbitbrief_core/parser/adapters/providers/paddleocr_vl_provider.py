from __future__ import annotations

import io
import os
import statistics
from pathlib import Path
from typing import Any

from .base import ProviderLayoutBlock, ProviderPdfHypothesis


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").replace("\x00", " ").split()).strip()


def _role_from_text(text: str) -> str:
    clean = text.strip()
    if not clean:
        return "noise"
    if "|" in clean or "\t" in clean:
        return "table"
    if clean.startswith(("-", "*", "•")):
        return "bullet"
    if len(clean) <= 90 and (clean.istitle() or clean.isupper()):
        return "heading"
    return "paragraph"


def _pdf_source(pdf_path: Path | None, pdf_bytes: bytes | None) -> bytes | None:
    if pdf_bytes is not None:
        return pdf_bytes
    if pdf_path is not None and pdf_path.exists():
        return pdf_path.read_bytes()
    return None


def extract_paddleocr_vl_pdf_hypothesis(*, pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> ProviderPdfHypothesis | None:
    """Primary OCR/VLM provider hypothesis for image-heavy PDFs."""
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        from paddleocr import PaddleOCR  # type: ignore
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

    try:
        ocr = PaddleOCR(use_textline_orientation=True, lang="en")
    except Exception:
        return None

    blocks: list[ProviderLayoutBlock] = []
    confidences: list[float] = []
    block_index = 0

    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
        image_payload: bytes = pix.tobytes("png")
        if not image_payload:
            continue
        image_array = cv2.imdecode(np.frombuffer(image_payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            continue
        try:
            # PaddleOCR 3.x prefers ndarray input and no cls kwarg.
            results = ocr.ocr(image_array) or []
        except Exception:
            continue
        page_rows = results[0] if isinstance(results, list) and results else None
        rec_texts = getattr(page_rows, "get", lambda *_args, **_kwargs: None)("rec_texts") if page_rows is not None else None
        rec_scores = getattr(page_rows, "get", lambda *_args, **_kwargs: None)("rec_scores") if page_rows is not None else None
        dt_polys = getattr(page_rows, "get", lambda *_args, **_kwargs: None)("dt_polys") if page_rows is not None else None

        if isinstance(rec_texts, list) and rec_texts:
            for idx, text in enumerate(rec_texts):
                normalized = _normalize(text)
                if not normalized:
                    continue
                score = 0.65
                if isinstance(rec_scores, list) and idx < len(rec_scores):
                    try:
                        score = max(0.0, min(1.0, float(rec_scores[idx])))
                    except Exception:
                        score = 0.65
                bbox = None
                if isinstance(dt_polys, list) and idx < len(dt_polys):
                    poly = dt_polys[idx]
                    try:
                        points = [(float(point[0]), float(point[1])) for point in poly]
                        x0 = min(point[0] for point in points)
                        y0 = min(point[1] for point in points)
                        x1 = max(point[0] for point in points)
                        y1 = max(point[1] for point in points)
                        bbox = (x0, y0, x1, y1)
                    except Exception:
                        bbox = None
                role = _role_from_text(normalized)
                blocks.append(
                    ProviderLayoutBlock(
                        block_id=f"paddleocr_vl_block:{page_index:04d}:{block_index:04d}",
                        page_index=page_index,
                        bbox=bbox,
                        text=normalized,
                        role=role,
                        confidence=score,
                        source="paddleocr_vl",
                        metadata={
                            "provider": "paddleocr_vl",
                            "ocr_confidence": score,
                            "reading_order_confidence": 0.72,
                            "degraded": False,
                        },
                    )
                )
                confidences.append(score)
                block_index += 1
            continue

        # Backward-compatible format fallback.
        for line in page_rows or []:
            try:
                points, (text, conf) = line
            except Exception:
                continue
            normalized = _normalize(text)
            if not normalized:
                continue
            try:
                x0 = min(float(point[0]) for point in points)
                y0 = min(float(point[1]) for point in points)
                x1 = max(float(point[0]) for point in points)
                y1 = max(float(point[1]) for point in points)
                bbox = (x0, y0, x1, y1)
            except Exception:
                bbox = None
            score = max(0.0, min(1.0, float(conf)))
            role = _role_from_text(normalized)
            blocks.append(
                ProviderLayoutBlock(
                    block_id=f"paddleocr_vl_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=bbox,
                    text=normalized,
                    role=role,
                    confidence=score,
                    source="paddleocr_vl",
                    metadata={
                        "provider": "paddleocr_vl",
                        "ocr_confidence": score,
                        "reading_order_confidence": 0.72,
                        "degraded": False,
                    },
                )
            )
            confidences.append(score)
            block_index += 1

    if not blocks:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id="hypothesis:paddleocr_vl",
        source="paddleocr_vl",
        page_blocks=tuple(blocks),
        table_regions=(),
        confidence=statistics.mean(confidences) if confidences else 0.0,
        metadata={
            "provider": "paddleocr_vl",
            "degraded": False,
            "page_count": len(doc),
            "block_count": len(blocks),
        },
    )
