from __future__ import annotations

import io
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.parser.adapters.arbitration import PageArbitrationResult, arbitrate_hypotheses
from orbitbrief_core.parser.adapters.providers.docling_provider import extract_docling_pdf_hypothesis
from orbitbrief_core.parser.adapters.providers.mineru_provider import extract_mineru_pdf_hypothesis
from orbitbrief_core.parser.adapters.providers.paddleocr_vl_provider import extract_paddleocr_vl_pdf_hypothesis
from orbitbrief_core.parser.adapters.providers.pp_structure_provider import extract_pp_structure_pdf_hypothesis
from orbitbrief_core.parser.adapters.providers.tesseract_provider import extract_tesseract_pdf_hypothesis


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


def _mineru_hypothesis(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> PdfParseHypothesis | None:
    provider_hypothesis = extract_mineru_pdf_hypothesis(pdf_path=pdf_path, pdf_bytes=pdf_bytes)
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


def _provider_hypothesis_to_canonical(provider_hypothesis: Any | None) -> PdfParseHypothesis | None:
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
        _docling_hypothesis(pdf_path, pdf_bytes),
        _mineru_hypothesis(pdf_path, pdf_bytes),
        _fitz_text_hypothesis(pdf_path, pdf_bytes),
        _pdfplumber_text_hypothesis(pdf_path, pdf_bytes),
        _pypdf_text_hypothesis(pdf_path, pdf_bytes),
    ]
    return tuple(h for h in hypotheses if h is not None)


def ocr_hypotheses(pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> tuple[PdfParseHypothesis, ...]:
    hypotheses = [
        _provider_hypothesis_to_canonical(extract_paddleocr_vl_pdf_hypothesis(pdf_path=pdf_path, pdf_bytes=pdf_bytes)),
        _provider_hypothesis_to_canonical(extract_pp_structure_pdf_hypothesis(pdf_path=pdf_path, pdf_bytes=pdf_bytes)),
        _mineru_hypothesis(pdf_path, pdf_bytes),
        _provider_hypothesis_to_canonical(extract_tesseract_pdf_hypothesis(pdf_path=pdf_path, pdf_bytes=pdf_bytes)),
        _fitz_text_hypothesis(pdf_path, pdf_bytes),
    ]
    return tuple(h for h in hypotheses if h is not None)
