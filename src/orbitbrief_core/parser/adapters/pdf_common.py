from __future__ import annotations

import io
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.adapters.providers.docling_provider import extract_docling_pdf_hypothesis


@dataclass(frozen=True, slots=True)
class LayoutBlockCandidate:
    block_id: str
    page_index: int
    bbox: tuple[float, float, float, float] | None
    text: str
    role: str
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TableRegionCandidate:
    region_id: str
    page_index: int
    bbox: tuple[float, float, float, float] | None
    text: str
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PdfParseHypothesis:
    hypothesis_id: str
    source: str
    page_blocks: tuple[LayoutBlockCandidate, ...]
    table_regions: tuple[TableRegionCandidate, ...]
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageArbitrationResult:
    selected_blocks: tuple[LayoutBlockCandidate, ...]
    selected_tables: tuple[TableRegionCandidate, ...]
    hypothesis_scores: Mapping[str, float]
    repeated_header_texts: tuple[str, ...] = ()
    repeated_footer_texts: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _normalize_block_text(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split()).strip()


def _classify_role(text: str, *, font_size: float | None = None, block_index: int | None = None) -> str:
    clean = text.strip()
    if not clean:
        return "noise"
    if clean.count("|") >= 2 or "\t" in clean:
        return "table"
    if len(clean) <= 80 and clean.isupper() and 2 <= len(clean.split()) <= 8:
        return "heading"
    if clean.startswith(("-", "*", "•")):
        return "bullet"
    if font_size is not None and font_size >= 13.0 and len(clean) <= 120:
        return "heading"
    if block_index == 0 and len(clean) <= 120:
        return "heading"
    return "paragraph"


def _compute_block_confidence(text: str, *, role: str, bonus: float = 0.0) -> float:
    density = min(1.0, len(text.strip()) / 180.0)
    role_bonus = 0.12 if role in {"heading", "paragraph", "bullet"} else 0.0
    return max(0.0, min(1.0, 0.45 + density * 0.35 + role_bonus + bonus))


def _pdf_bytes(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> bytes | None:
    if pdf_bytes is not None:
        return pdf_bytes
    if pdf_path is not None and pdf_path.exists():
        return pdf_path.read_bytes()
    return None


def _fitz_text_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None

    raw = _pdf_bytes(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        doc = fitz.open(stream=raw, filetype="pdf") if raw is not None else fitz.open(pdf_path)
    except Exception:
        return None

    blocks: list[LayoutBlockCandidate] = []
    tables: list[TableRegionCandidate] = []
    font_sizes: list[float] = []
    block_index = 0
    for page_index, page in enumerate(doc):
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            lines = block.get("lines", [])
            if not lines:
                continue
            text_parts: list[str] = []
            page_font_sizes: list[float] = []
            for line in lines:
                for span in line.get("spans", []):
                    span_text = str(span.get("text", ""))
                    if span_text:
                        text_parts.append(span_text)
                        size = span.get("size")
                        if isinstance(size, (int, float)):
                            page_font_sizes.append(float(size))
            text = _normalize_block_text(" ".join(text_parts))
            if not text:
                continue
            font_size = statistics.mean(page_font_sizes) if page_font_sizes else None
            if font_size is not None:
                font_sizes.append(font_size)
            bbox = tuple(block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
            role = _classify_role(text, font_size=font_size, block_index=block_index)
            confidence = _compute_block_confidence(text, role=role, bonus=0.1)
            block_id = f"fitz_block:{page_index:04d}:{block_index:04d}"
            candidate = LayoutBlockCandidate(
                block_id=block_id,
                page_index=page_index,
                bbox=bbox,
                text=text,
                role=role,
                confidence=confidence,
                source="fitz",
                metadata={"font_size": font_size},
            )
            blocks.append(candidate)
            if role == "table":
                tables.append(
                    TableRegionCandidate(
                        region_id=f"fitz_table:{page_index:04d}:{block_index:04d}",
                        page_index=page_index,
                        bbox=bbox,
                        text=text,
                        confidence=confidence,
                        source="fitz",
                        metadata={"font_size": font_size},
                    )
                )
            block_index += 1
    mean_font = statistics.mean(font_sizes) if font_sizes else None
    confidence = 0.85 if blocks else 0.0
    return PdfParseHypothesis(
        hypothesis_id="hypothesis:fitz",
        source="fitz",
        page_blocks=tuple(blocks),
        table_regions=tuple(tables),
        confidence=confidence,
        metadata={"mean_font_size": mean_font, "page_count": len(doc)},
    )


def _pdfplumber_text_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return None

    raw = _pdf_bytes(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        pdf = pdfplumber.open(io.BytesIO(raw)) if raw is not None else pdfplumber.open(str(pdf_path))
    except Exception:
        return None

    blocks: list[LayoutBlockCandidate] = []
    tables: list[TableRegionCandidate] = []
    block_index = 0
    for page_index, page in enumerate(pdf.pages):
        try:
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
        except Exception:
            words = []
        if not words:
            extracted = page.extract_text() or ""
            for para_index, paragraph in enumerate(p for p in extracted.split("\n\n") if p.strip()):
                text = _normalize_block_text(paragraph)
                role = _classify_role(text, block_index=para_index)
                confidence = _compute_block_confidence(text, role=role)
                blocks.append(
                    LayoutBlockCandidate(
                        block_id=f"plumber_block:{page_index:04d}:{block_index:04d}",
                        page_index=page_index,
                        bbox=None,
                        text=text,
                        role=role,
                        confidence=confidence,
                        source="pdfplumber",
                    )
                )
                block_index += 1
            continue

        line_groups: dict[float, list[dict[str, Any]]] = {}
        for word in words:
            top = round(float(word.get("top", 0.0)), 1)
            line_groups.setdefault(top, []).append(word)
        for _, line_words in sorted(line_groups.items(), key=lambda item: item[0]):
            ordered = sorted(line_words, key=lambda item: float(item.get("x0", 0.0)))
            text = _normalize_block_text(" ".join(str(word.get("text", "")) for word in ordered))
            if not text:
                continue
            x0 = min(float(word.get("x0", 0.0)) for word in ordered)
            top = min(float(word.get("top", 0.0)) for word in ordered)
            x1 = max(float(word.get("x1", 0.0)) for word in ordered)
            bottom = max(float(word.get("bottom", 0.0)) for word in ordered)
            role = _classify_role(text)
            confidence = _compute_block_confidence(text, role=role, bonus=0.04)
            blocks.append(
                LayoutBlockCandidate(
                    block_id=f"plumber_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=(x0, top, x1, bottom),
                    text=text,
                    role=role,
                    confidence=confidence,
                    source="pdfplumber",
                )
            )
            if role == "table":
                tables.append(
                    TableRegionCandidate(
                        region_id=f"plumber_table:{page_index:04d}:{block_index:04d}",
                        page_index=page_index,
                        bbox=(x0, top, x1, bottom),
                        text=text,
                        confidence=confidence,
                        source="pdfplumber",
                    )
                )
            block_index += 1
    confidence = 0.75 if blocks else 0.0
    return PdfParseHypothesis(
        hypothesis_id="hypothesis:pdfplumber",
        source="pdfplumber",
        page_blocks=tuple(blocks),
        table_regions=tuple(tables),
        confidence=confidence,
        metadata={"page_count": len(pdf.pages)},
    )


def _pypdf_text_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    try:
        import pypdf  # type: ignore
    except Exception:
        return None
    raw = _pdf_bytes(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw)) if raw is not None else pypdf.PdfReader(str(pdf_path))
    except Exception:
        return None

    blocks: list[LayoutBlockCandidate] = []
    block_index = 0
    for page_index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if not text.strip():
            continue
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        for paragraph in paragraphs:
            normalized = _normalize_block_text(paragraph)
            role = _classify_role(normalized)
            confidence = _compute_block_confidence(normalized, role=role, bonus=-0.08)
            blocks.append(
                LayoutBlockCandidate(
                    block_id=f"pypdf_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=None,
                    text=normalized,
                    role=role,
                    confidence=confidence,
                    source="pypdf",
                )
            )
            block_index += 1
    confidence = 0.55 if blocks else 0.0
    return PdfParseHypothesis(
        hypothesis_id="hypothesis:pypdf",
        source="pypdf",
        page_blocks=tuple(blocks),
        table_regions=(),
        confidence=confidence,
        metadata={"page_count": len(reader.pages)},
    )


def _docling_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    provider_hypothesis = extract_docling_pdf_hypothesis(pdf_path=pdf_path, pdf_bytes=pdf_bytes)
    if provider_hypothesis is None:
        return None
    return PdfParseHypothesis(
        hypothesis_id=provider_hypothesis.hypothesis_id,
        source=provider_hypothesis.source,
        page_blocks=tuple(
            LayoutBlockCandidate(
                block_id=block.block_id,
                page_index=block.page_index,
                bbox=block.bbox,
                text=_normalize_block_text(block.text),
                role=block.role,
                confidence=block.confidence,
                source=block.source,
                metadata=dict(block.metadata),
            )
            for block in provider_hypothesis.page_blocks
            if _normalize_block_text(block.text)
        ),
        table_regions=tuple(
            TableRegionCandidate(
                region_id=region.region_id,
                page_index=region.page_index,
                bbox=region.bbox,
                text=_normalize_block_text(region.text),
                confidence=region.confidence,
                source=region.source,
                metadata=dict(region.metadata),
            )
            for region in provider_hypothesis.table_regions
            if _normalize_block_text(region.text)
        ),
        confidence=provider_hypothesis.confidence,
        metadata=dict(provider_hypothesis.metadata),
    )


def text_hypotheses(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> tuple[PdfParseHypothesis, ...]:
    hypotheses = [
        _fitz_text_hypothesis(pdf_path, pdf_bytes),
        _pdfplumber_text_hypothesis(pdf_path, pdf_bytes),
        _pypdf_text_hypothesis(pdf_path, pdf_bytes),
        _docling_hypothesis(pdf_path, pdf_bytes),
    ]
    return tuple(h for h in hypotheses if h is not None)


def _repeated_margin_texts(blocks: Sequence[LayoutBlockCandidate], *, margin_threshold: float = 120.0) -> tuple[tuple[str, ...], tuple[str, ...]]:
    headers: dict[str, set[int]] = {}
    footers: dict[str, set[int]] = {}
    pages = {block.page_index for block in blocks}
    if not pages:
        return (), ()
    for block in blocks:
        if block.bbox is None:
            continue
        x0, y0, x1, y1 = block.bbox
        text = _normalize_block_text(block.text).lower()
        if not text or len(text) > 120:
            continue
        if y0 <= margin_threshold:
            headers.setdefault(text, set()).add(block.page_index)
        if y1 >= 700.0:
            footers.setdefault(text, set()).add(block.page_index)
    page_threshold = max(2, math.ceil(len(pages) * 0.6))
    repeated_headers = tuple(sorted(text for text, page_ids in headers.items() if len(page_ids) >= page_threshold))
    repeated_footers = tuple(sorted(text for text, page_ids in footers.items() if len(page_ids) >= page_threshold))
    return repeated_headers, repeated_footers


def arbitrate_hypotheses(hypotheses: Sequence[PdfParseHypothesis]) -> PageArbitrationResult:
    if not hypotheses:
        return PageArbitrationResult(selected_blocks=(), selected_tables=(), hypothesis_scores={}, disagreements=("no_hypotheses",))
    scores: dict[str, float] = {}
    disagreements: list[str] = []
    for hypothesis in hypotheses:
        text_chars = sum(len(block.text) for block in hypothesis.page_blocks)
        block_count = len(hypothesis.page_blocks)
        heading_bonus = sum(1 for block in hypothesis.page_blocks if block.role == "heading") * 2.0
        table_bonus = len(hypothesis.table_regions) * 1.5
        quality = hypothesis.confidence * 100.0 + min(200.0, text_chars / 12.0) + min(40.0, block_count * 1.2) + heading_bonus + table_bonus
        scores[hypothesis.hypothesis_id] = round(quality, 6)
    ranked = sorted(hypotheses, key=lambda item: scores[item.hypothesis_id], reverse=True)
    winner = ranked[0]
    if len(ranked) > 1 and abs(scores[ranked[0].hypothesis_id] - scores[ranked[1].hypothesis_id]) <= 12.0:
        disagreements.append(f"close_pdf_hypotheses:{ranked[0].source}:{ranked[1].source}")
    repeated_headers, repeated_footers = _repeated_margin_texts(winner.page_blocks)
    filtered_blocks = tuple(
        block
        for block in winner.page_blocks
        if _normalize_block_text(block.text).lower() not in set(repeated_headers + repeated_footers)
    )
    return PageArbitrationResult(
        selected_blocks=filtered_blocks,
        selected_tables=winner.table_regions,
        hypothesis_scores=scores,
        repeated_header_texts=repeated_headers,
        repeated_footer_texts=repeated_footers,
        disagreements=tuple(disagreements),
        metadata={"winner": winner.source, "winner_hypothesis_id": winner.hypothesis_id},
    )


def _pytesseract_ocr_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return None

    raw = _pdf_bytes(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        doc = fitz.open(stream=raw, filetype="pdf") if raw is not None else fitz.open(pdf_path)
    except Exception:
        return None

    blocks: list[LayoutBlockCandidate] = []
    block_index = 0
    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        mode = "RGB" if pix.n >= 3 else "L"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        rows: dict[tuple[int, int, int], list[int]] = {}
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
            rows.setdefault(key, []).append(i)
        for _, idxs in sorted(rows.items()):
            texts = [str(data["text"][i]).strip() for i in idxs if str(data["text"][i]).strip()]
            if not texts:
                continue
            confs = [max(0.0, float(data["conf"][i])) for i in idxs if str(data["text"][i]).strip()]
            x0 = min(int(data["left"][i]) for i in idxs)
            y0 = min(int(data["top"][i]) for i in idxs)
            x1 = max(int(data["left"][i]) + int(data["width"][i]) for i in idxs)
            y1 = max(int(data["top"][i]) + int(data["height"][i]) for i in idxs)
            text = _normalize_block_text(" ".join(texts))
            role = _classify_role(text)
            conf = max(0.0, min(1.0, (statistics.mean(confs) / 100.0) if confs else 0.0))
            blocks.append(
                LayoutBlockCandidate(
                    block_id=f"ocr_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    text=text,
                    role=role,
                    confidence=conf,
                    source="pytesseract",
                )
            )
            block_index += 1
    if not blocks:
        return None
    conf = statistics.mean(block.confidence for block in blocks)
    return PdfParseHypothesis(
        hypothesis_id="hypothesis:pytesseract",
        source="pytesseract",
        page_blocks=tuple(blocks),
        table_regions=(),
        confidence=conf,
        metadata={"page_count": len(doc)},
    )


def _paddle_ocr_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    try:
        from paddleocr import PaddleOCR  # type: ignore
        import fitz  # type: ignore
    except Exception:
        return None
    raw = _pdf_bytes(pdf_path, pdf_bytes)
    if raw is None and pdf_path is None:
        return None
    try:
        doc = fitz.open(stream=raw, filetype="pdf") if raw is not None else fitz.open(pdf_path)
    except Exception:
        return None
    ocr = PaddleOCR(use_angle_cls=True, lang="en")
    blocks: list[LayoutBlockCandidate] = []
    block_index = 0
    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img_bytes = pix.tobytes("png")
        results = ocr.ocr(img_bytes, cls=True) or []
        for line in results[0] if results else []:
            points, (text, conf) = line
            x0 = min(point[0] for point in points)
            y0 = min(point[1] for point in points)
            x1 = max(point[0] for point in points)
            y1 = max(point[1] for point in points)
            normalized = _normalize_block_text(text)
            if not normalized:
                continue
            role = _classify_role(normalized)
            blocks.append(
                LayoutBlockCandidate(
                    block_id=f"paddle_ocr_block:{page_index:04d}:{block_index:04d}",
                    page_index=page_index,
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    text=normalized,
                    role=role,
                    confidence=max(0.0, min(1.0, float(conf))),
                    source="paddleocr",
                )
            )
            block_index += 1
    if not blocks:
        return None
    conf = statistics.mean(block.confidence for block in blocks)
    return PdfParseHypothesis(
        hypothesis_id="hypothesis:paddleocr",
        source="paddleocr",
        page_blocks=tuple(blocks),
        table_regions=(),
        confidence=conf,
        metadata={"page_count": len(doc)},
    )


def ocr_hypotheses(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> tuple[PdfParseHypothesis, ...]:
    hypotheses = [
        _paddle_ocr_hypothesis(pdf_path, pdf_bytes),
        _pytesseract_ocr_hypothesis(pdf_path, pdf_bytes),
        _fitz_text_hypothesis(pdf_path, pdf_bytes),
    ]
    return tuple(h for h in hypotheses if h is not None)
