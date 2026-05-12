from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .base import ProviderLayoutBlock, ProviderPdfHypothesis, ProviderTableRegion

_ROLE_CONFIDENCE = {
    "heading": 0.85,
    "paragraph": 0.75,
    "bullet": 0.72,
    "table": 0.78,
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def _safe_get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _extract_bbox(obj: Any) -> tuple[float, float, float, float] | None:
    raw = _safe_get(obj, "bbox", "box")
    if isinstance(raw, Sequence) and len(raw) >= 4:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except Exception:
            return None
    if isinstance(raw, Mapping):
        x0 = _safe_get(raw, "x0", "left")
        y0 = _safe_get(raw, "y0", "top")
        x1 = _safe_get(raw, "x1", "right")
        y1 = _safe_get(raw, "y1", "bottom")
        if all(isinstance(v, (int, float)) for v in (x0, y0, x1, y1)):
            return (float(x0), float(y0), float(x1), float(y1))
    return None


def _extract_page_index(obj: Any) -> int:
    raw = _safe_get(obj, "page_index", "page_idx", "page_no", "page_number", "page")
    if isinstance(raw, (int, float)):
        idx = int(raw)
        if idx < 0:
            return 0
        # Docling page numbers are often 1-based.
        return max(0, idx - 1) if idx > 0 else 0
    return 0


def _resolve_role(label: str | None, text: str) -> str:
    hint = (label or "").strip().lower()
    if "head" in hint or hint in {"title", "section_title"}:
        return "heading"
    if "list" in hint or "bullet" in hint or "item" in hint:
        return "bullet"
    if "table" in hint:
        return "table"
    if text.startswith(("-", "*", "•")):
        return "bullet"
    return "paragraph"


def _collect_table_text(node: Any) -> str:
    text = _clean_text(_safe_get(node, "text", "content", "markdown"))
    if text:
        return text
    rows = _safe_get(node, "rows", "cells")
    if not isinstance(rows, Sequence):
        return ""
    parts: list[str] = []
    for row in rows:
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            cells = [_clean_text(cell) for cell in row]
            line = " | ".join(cell for cell in cells if cell)
            if line:
                parts.append(line)
        else:
            line = _clean_text(row)
            if line:
                parts.append(line)
    return " ; ".join(parts)


def _iter_nodes(value: Any) -> list[Any]:
    collected: list[Any] = []
    stack = [value]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        oid = id(current)
        if oid in seen:
            continue
        seen.add(oid)
        collected.append(current)
        if isinstance(current, Mapping):
            for child in current.values():
                if isinstance(child, (Mapping, list, tuple)):
                    stack.append(child)
            continue
        if isinstance(current, (list, tuple)):
            for child in current:
                if isinstance(child, (Mapping, list, tuple)) or hasattr(child, "__dict__"):
                    stack.append(child)
            continue
        for attr in ("children", "items", "blocks", "elements"):
            child = _safe_get(current, attr)
            if isinstance(child, (list, tuple)):
                stack.append(child)
    return collected


def _extract_structured_blocks(document: Any, *, source_path: str | None) -> tuple[tuple[ProviderLayoutBlock, ...], tuple[ProviderTableRegion, ...]]:
    blocks: list[ProviderLayoutBlock] = []
    tables: list[ProviderTableRegion] = []
    block_index = 0
    table_index = 0

    root_data = None
    for exporter in ("export_to_dict", "to_dict"):
        method = _safe_get(document, exporter)
        if callable(method):
            try:
                root_data = method()
                break
            except Exception:
                root_data = None

    seed = root_data if root_data is not None else document
    candidate_nodes: list[Any] = []
    direct_blocks = _safe_get(seed, "blocks")
    if isinstance(direct_blocks, Sequence):
        candidate_nodes.extend(direct_blocks)
    # Keep generic traversal as a fallback, but evaluate direct blocks first.
    candidate_nodes.extend(_iter_nodes(seed))
    seen_node_ids: set[int] = set()
    for node in candidate_nodes:
        node_id = id(node)
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        label = _safe_get(node, "label", "type", "kind", "category", "name")
        label_text = str(label).strip().lower() if label is not None else ""
        is_table = "table" in label_text
        text = _collect_table_text(node) if is_table else _clean_text(_safe_get(node, "text", "content", "value", "markdown"))
        if not text:
            continue
        page_index = _extract_page_index(node)
        bbox = _extract_bbox(node)
        role = "table" if is_table else _resolve_role(label_text or None, text)
        confidence = _ROLE_CONFIDENCE.get(role, 0.70)
        metadata = {
            "provider": "docling",
            "docling_label": label_text or "unknown",
            "source_path": source_path,
            "degraded": False,
        }
        if role == "table":
            region_id = f"docling_table:{page_index:04d}:{table_index:04d}"
            table = ProviderTableRegion(
                region_id=region_id,
                page_index=page_index,
                bbox=bbox,
                text=text,
                confidence=confidence,
                source="docling",
                metadata=metadata,
            )
            tables.append(table)
            table_index += 1
            # Also keep table blocks in the layout stream for section-aware parsing.
            block_id = f"docling_block:{page_index:04d}:{block_index:04d}"
            blocks.append(
                ProviderLayoutBlock(
                    block_id=block_id,
                    page_index=page_index,
                    bbox=bbox,
                    text=text,
                    role="table",
                    confidence=confidence,
                    source="docling",
                    metadata={**metadata, "table_region_id": region_id},
                )
            )
            block_index += 1
            continue
        block_id = f"docling_block:{page_index:04d}:{block_index:04d}"
        blocks.append(
            ProviderLayoutBlock(
                block_id=block_id,
                page_index=page_index,
                bbox=bbox,
                text=text,
                role=role,
                confidence=confidence,
                source="docling",
                metadata=metadata,
            )
        )
        block_index += 1
    return tuple(blocks), tuple(tables)


def _markdown_fallback(document: Any, *, source_path: str | None) -> tuple[ProviderLayoutBlock, ...]:
    markdown = ""
    export = _safe_get(document, "export_to_markdown")
    if callable(export):
        try:
            markdown = str(export())
        except Exception:
            markdown = ""
    if not markdown:
        return ()
    chunks = [_clean_text(chunk) for chunk in markdown.split("\n\n") if _clean_text(chunk)]
    out: list[ProviderLayoutBlock] = []
    for index, chunk in enumerate(chunks):
        role = "heading" if chunk.startswith("#") else _resolve_role(None, chunk)
        out.append(
            ProviderLayoutBlock(
                block_id=f"docling_fallback_block:{index:04d}",
                page_index=0,
                bbox=None,
                text=chunk,
                role=role,
                confidence=0.62,
                source="docling",
                metadata={
                    "provider": "docling",
                    "docling_label": "markdown_fallback",
                    "source_path": source_path,
                    "degraded": True,
                },
            )
        )
    return tuple(out)


def extract_docling_pdf_hypothesis(*, pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> ProviderPdfHypothesis | None:
    """Extract Docling provider-scoped PDF hypothesis for arbitration."""

    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception:
        return None
    if pdf_path is None:
        return None
    try:
        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
    except Exception:
        return None
    document = _safe_get(result, "document")
    if document is None:
        return None

    blocks, tables = _extract_structured_blocks(document, source_path=str(pdf_path))
    if blocks:
        confidence = min(0.95, 0.72 + min(0.20, len(blocks) * 0.01) + min(0.08, len(tables) * 0.01))
        return ProviderPdfHypothesis(
            hypothesis_id="hypothesis:docling",
            source="docling",
            page_blocks=blocks,
            table_regions=tables,
            confidence=confidence,
            metadata={
                "provider": "docling",
                "degraded": False,
                "source_path": str(pdf_path),
                "block_count": len(blocks),
                "table_count": len(tables),
            },
        )

    fallback_blocks = _markdown_fallback(document, source_path=str(pdf_path))
    if not fallback_blocks:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=fallback_blocks,
        table_regions=(),
        confidence=0.62,
        metadata={"provider": "docling", "degraded": True, "source_path": str(pdf_path)},
    )
