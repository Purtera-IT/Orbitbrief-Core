from __future__ import annotations

import sys
import types
from pathlib import Path

from orbitbrief_core.parser.adapters.pdf_common import (
    LayoutBlockCandidate,
    PdfParseHypothesis,
    TableRegionCandidate,
    arbitrate_hypotheses,
    text_hypotheses,
)
from orbitbrief_core.parser.adapters.providers.mineru_provider import extract_mineru_pdf_hypothesis


def _install_fake_mineru(monkeypatch, *, document_obj) -> None:
    class _Result:
        def __init__(self, document):
            self.document = document

    class _Converter:
        def convert(self, _path: str):
            return _Result(document_obj)

    mineru_pkg = types.ModuleType("mineru")
    converter_mod = types.ModuleType("mineru.document_converter")
    converter_mod.DocumentConverter = _Converter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mineru", mineru_pkg)
    monkeypatch.setitem(sys.modules, "mineru.document_converter", converter_mod)


def test_mineru_provider_emits_structured_hypothesis(monkeypatch, tmp_path: Path) -> None:
    class _Doc:
        def to_dict(self):
            return {
                "blocks": [
                    {"label": "heading", "page_no": 1, "bbox": [1, 2, 120, 42], "text": "Deliverables"},
                    {"label": "paragraph", "page_no": 1, "bbox": [1, 50, 340, 130], "text": "Install edge switch and configure uplink."},
                    {"label": "table", "page_no": 2, "bbox": [2, 150, 420, 280], "rows": [["Site", "Qty"], ["HQ", "4"]]},
                ]
            }

        def export_to_markdown(self):
            return "# Deliverables\nInstall edge switch and configure uplink."

    _install_fake_mineru(monkeypatch, document_obj=_Doc())
    pdf_path = tmp_path / "mineru.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% mineru stub")

    hypothesis = extract_mineru_pdf_hypothesis(pdf_path=pdf_path)

    assert hypothesis is not None
    assert hypothesis.source == "mineru"
    assert hypothesis.metadata.get("degraded") is False
    assert len(hypothesis.page_blocks) >= 3
    assert len(hypothesis.table_regions) == 1
    assert {block.page_index for block in hypothesis.page_blocks} == {0, 1}


def test_text_hypotheses_includes_mineru(monkeypatch) -> None:
    mineru = PdfParseHypothesis(
        hypothesis_id="hypothesis:mineru",
        source="mineru",
        page_blocks=(LayoutBlockCandidate("m1", 0, None, "Heading", "heading", 0.8, "mineru"),),
        table_regions=(),
        confidence=0.8,
        metadata={"degraded": False},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._docling_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._mineru_hypothesis", lambda *_args, **_kwargs: mineru)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._fitz_text_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._pdfplumber_text_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._pypdf_text_hypothesis", lambda *_args, **_kwargs: None)

    hypotheses = text_hypotheses()
    assert len(hypotheses) == 1
    assert hypotheses[0].source == "mineru"


def test_arbitration_emits_reason_codes_for_disputes() -> None:
    docling = PdfParseHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=(
            LayoutBlockCandidate("d1", 0, (0.0, 10.0, 120.0, 30.0), "Scope", "heading", 0.86, "docling"),
            LayoutBlockCandidate("d2", 0, (0.0, 40.0, 320.0, 80.0), "Install 4 sites", "paragraph", 0.78, "docling"),
            LayoutBlockCandidate("d3", 0, (0.0, 90.0, 320.0, 120.0), "Site | Qty", "table", 0.80, "docling"),
        ),
        table_regions=(TableRegionCandidate("dt1", 0, None, "Site | Qty", 0.80, "docling"),),
        confidence=0.88,
        metadata={"degraded": False},
    )
    mineru = PdfParseHypothesis(
        hypothesis_id="hypothesis:mineru",
        source="mineru",
        page_blocks=(
            LayoutBlockCandidate("m1", 0, (0.0, 10.0, 120.0, 30.0), "Scope", "paragraph", 0.75, "mineru"),
            LayoutBlockCandidate("m2", 0, (0.0, 45.0, 320.0, 85.0), "Site | Qty", "paragraph", 0.74, "mineru"),
            LayoutBlockCandidate("m3", 0, (0.0, 90.0, 320.0, 120.0), "Install 4 sites", "paragraph", 0.73, "mineru"),
        ),
        table_regions=(),
        confidence=0.82,
        metadata={"degraded": False},
    )

    result = arbitrate_hypotheses((docling, mineru))
    reason_codes = set(result.metadata.get("arbitration_reason_codes", ()))
    assert "reading_order_dispute" in reason_codes
    assert "heading_body_dispute" in reason_codes
    assert "section_boundary_dispute" in reason_codes
    assert "table_attachment_dispute" in reason_codes
    assert result.metadata.get("winner") in {"docling", "mineru"}
    assert isinstance(result.metadata.get("competing_sources"), list)

    # Winner provenance metadata should be present on selected blocks.
    assert result.selected_blocks
    span_meta = result.selected_blocks[0].metadata
    assert "winner_hypothesis_id" in span_meta
    assert "winner_source" in span_meta
    assert "arbitration_reason_codes" in span_meta
