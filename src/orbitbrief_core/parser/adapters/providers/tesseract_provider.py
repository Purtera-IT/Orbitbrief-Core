from __future__ import annotations

import statistics
from pathlib import Path

from .base import ProviderLayoutBlock, ProviderPdfHypothesis


def _normalize(text: str) -> str:
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


def extract_tesseract_pdf_hypothesis(*, pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> ProviderPdfHypothesis | None:
    """Fallback OCR provider hypothesis using Tesseract."""
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
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
    confidences: list[float] = []
    block_index = 0
    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        mode = "RGB" if pix.n >= 3 else "L"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        row_groups: dict[tuple[int, int, int], list[int]] = {}
        n = len(data.get("text", []))
        for i in range(n):
            text = str(data["text"][i]).strip()
            conf_text = str(data["conf"][i]).strip()
            try:
                conf = float(conf_text)
            except Exception:
                conf = -1.0
            if not text or conf < 0:
                continue
            key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            row_groups.setdefault(key, []).append(i)
        for _, indices in sorted(row_groups.items()):
            texts = [str(data["text"][i]).strip() for i in indices if str(data["text"][i]).strip()]
            if not texts:
                continue
            normalized = _normalize(" ".join(texts))
            if not normalized:
                continue
            confs = [max(0.0, float(data["conf"][i])) for i in indices if str(data["text"][i]).strip()]
            score = max(0.0, min(1.0, (statistics.mean(confs) / 100.0) if confs else 0.0))
            x0 = min(int(data["left"][i]) for i in indices)
            y0 = min(int(data["top"][i]) for i in indices)
            x1 = max(int(data["left"][i]) + int(data["width"][i]) for i in indices)
            y1 = max(int(data["top"][i]) + int(data["height"][i]) for i in indices)
            blocks.append(
                ProviderLayoutBlock(
                    block_id=f"tesseract_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    text=normalized,
                    role=_role_from_text(normalized),
                    confidence=score,
                    source="tesseract",
                    metadata={
                        "provider": "tesseract",
                        "ocr_confidence": score,
                        "reading_order_confidence": 0.55,
                        "degraded": True,
                    },
                )
            )
            confidences.append(score)
            block_index += 1
    if not blocks:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id="hypothesis:tesseract",
        source="tesseract",
        page_blocks=tuple(blocks),
        table_regions=(),
        confidence=statistics.mean(confidences) if confidences else 0.0,
        metadata={"provider": "tesseract", "degraded": True, "block_count": len(blocks)},
    )
