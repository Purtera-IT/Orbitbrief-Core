from __future__ import annotations

from pathlib import Path

from .base import ProviderLayoutBlock, ProviderPdfHypothesis


def extract_docling_pdf_hypothesis(*, pdf_path: Path | None = None, pdf_bytes: bytes | None = None) -> ProviderPdfHypothesis | None:
    """Best-effort Docling provider shim for Stage 3 adapter integration.

    This intentionally returns a provider-scoped hypothesis object so adapter
    arbitration stays in pdf_common.py while model/provider-specific logic lives
    in a dedicated module.
    """

    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception:
        return None
    if pdf_path is None:
        return None
    try:
        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
        markdown = result.document.export_to_markdown()  # type: ignore[attr-defined]
    except Exception:
        return None
    text = " ".join(str(markdown).replace("\x00", " ").split()).strip()
    if not text:
        return None
    return ProviderPdfHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=(
            ProviderLayoutBlock(
                block_id="docling_block:0000:0000",
                page_index=0,
                bbox=None,
                text=text,
                role="paragraph",
                confidence=0.7,
                source="docling",
                metadata={"degraded": True},
            ),
        ),
        table_regions=(),
        confidence=0.7,
        metadata={"degraded": True, "provider": "docling"},
    )
