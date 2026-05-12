from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

from orbitbrief_core.parser.adapters.pdf_common import (
    LayoutBlockCandidate,
    PageArbitrationResult,
    PdfParseHypothesis,
    TableRegionCandidate,
    arbitrate_hypotheses,
    text_hypotheses,
)
from orbitbrief_core.parser.adapters.providers.docling_provider import extract_docling_pdf_hypothesis
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import route_and_parse


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [{"modality": "pdf_text", "parser_profile_id": "parser:professional_services_text:pdf_text"}]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _install_fake_docling(monkeypatch, *, document_obj) -> None:
    class _Result:
        def __init__(self, document):
            self.document = document

    class _Converter:
        def convert(self, _path: str):
            return _Result(document_obj)

    docling_pkg = types.ModuleType("docling")
    converter_mod = types.ModuleType("docling.document_converter")
    converter_mod.DocumentConverter = _Converter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docling", docling_pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_mod)


def test_docling_provider_emits_structured_page_backed_blocks(monkeypatch, tmp_path: Path) -> None:
    class _Doc:
        def to_dict(self):
            return {
                "blocks": [
                    {"label": "heading", "page_no": 1, "bbox": [1, 2, 100, 40], "text": "Scope"},
                    {"label": "paragraph", "page_no": 1, "bbox": [1, 50, 300, 120], "text": "Install core and edge services."},
                    {"label": "table", "page_no": 2, "bbox": [1, 140, 400, 260], "rows": [["Site", "Qty"], ["HQ", "3"]]},
                ]
            }

        def export_to_markdown(self):
            return "# Scope\nInstall core and edge services."

    _install_fake_docling(monkeypatch, document_obj=_Doc())
    pdf_path = tmp_path / "memo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% stub")

    hypothesis = extract_docling_pdf_hypothesis(pdf_path=pdf_path)

    assert hypothesis is not None
    assert hypothesis.metadata.get("degraded") is False
    assert len(hypothesis.page_blocks) >= 3
    assert {block.page_index for block in hypothesis.page_blocks} == {0, 1}
    assert any(block.role == "heading" for block in hypothesis.page_blocks)
    assert len(hypothesis.table_regions) == 1


def test_docling_provider_falls_back_to_degraded_markdown(monkeypatch, tmp_path: Path) -> None:
    class _Doc:
        def to_dict(self):
            return {}

        def export_to_markdown(self):
            return "# Header\n\nPlain paragraph"

    _install_fake_docling(monkeypatch, document_obj=_Doc())
    pdf_path = tmp_path / "memo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% stub")

    hypothesis = extract_docling_pdf_hypothesis(pdf_path=pdf_path)

    assert hypothesis is not None
    assert hypothesis.metadata.get("degraded") is True
    assert len(hypothesis.page_blocks) >= 1


def test_arbitration_prefers_non_degraded_docling_structure() -> None:
    docling = PdfParseHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=(
            LayoutBlockCandidate("d1", 0, None, "Scope", "heading", 0.85, "docling"),
            LayoutBlockCandidate("d2", 0, None, "Build parser runtime spine", "paragraph", 0.78, "docling"),
            LayoutBlockCandidate("d3", 1, None, "Deliverables and exclusions", "paragraph", 0.76, "docling"),
        ),
        table_regions=(TableRegionCandidate("dt1", 1, None, "Site | Qty", 0.80, "docling"),),
        confidence=0.86,
        metadata={"degraded": False},
    )
    fitz = PdfParseHypothesis(
        hypothesis_id="hypothesis:fitz",
        source="fitz",
        page_blocks=(LayoutBlockCandidate("f1", 0, None, "Scope and delivery", "paragraph", 0.80, "fitz"),),
        table_regions=(),
        confidence=0.84,
        metadata={},
    )
    result = arbitrate_hypotheses((docling, fitz))
    assert result.metadata.get("winner") == "docling"
    assert result.metadata.get("winner_hypothesis_id") == "hypothesis:docling"
    assert result.hypothesis_scores["hypothesis:docling"] > result.hypothesis_scores["hypothesis:fitz"]


def test_text_hypotheses_falls_back_when_docling_unavailable(monkeypatch) -> None:
    fitz = PdfParseHypothesis(
        hypothesis_id="hypothesis:fitz",
        source="fitz",
        page_blocks=(LayoutBlockCandidate("f1", 0, None, "Fallback block", "paragraph", 0.7, "fitz"),),
        table_regions=(),
        confidence=0.70,
        metadata={},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._docling_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._fitz_text_hypothesis", lambda *_args, **_kwargs: fitz)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._pdfplumber_text_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._pypdf_text_hypothesis", lambda *_args, **_kwargs: None)

    hypotheses = text_hypotheses(pdf_path=None, pdf_bytes=None)
    assert len(hypotheses) == 1
    assert hypotheses[0].source == "fitz"


def test_pdf_text_emits_winner_provenance_on_spans(monkeypatch) -> None:
    dummy_hypothesis = PdfParseHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=(LayoutBlockCandidate("dummy", 0, None, "dummy", "paragraph", 0.6, "docling"),),
        table_regions=(),
        confidence=0.6,
        metadata={"degraded": False},
    )
    arbitration = PageArbitrationResult(
        selected_blocks=(
            LayoutBlockCandidate("b1", 0, None, "Scope", "heading", 0.9, "docling", {"provider": "docling"}),
            LayoutBlockCandidate("b2", 0, None, "Install 3 sites", "paragraph", 0.8, "docling", {"provider": "docling"}),
            LayoutBlockCandidate("b3", 0, None, "Site | Qty", "table", 0.8, "docling", {"provider": "docling"}),
        ),
        selected_tables=(TableRegionCandidate("t1", 0, None, "Site | Qty", 0.8, "docling"),),
        hypothesis_scores={"hypothesis:docling": 220.0},
        metadata={"winner": "docling", "winner_hypothesis_id": "hypothesis:docling"},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_text.text_hypotheses", lambda **_kwargs: (dummy_hypothesis,))
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_text.arbitrate_hypotheses", lambda _hypotheses: arbitration)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="doc_pdf_text_docling_001",
        filename="memo.pdf",
        mime_type="application/pdf",
        raw_text_preview="Scope",
        metadata={"native_text_ratio": 0.98},
    )
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    assert plan.adapter_chain[0] == "pdf_text"
    assert parsed.evidence_spans
    first_span_meta = parsed.evidence_spans[0].metadata
    assert first_span_meta.get("winner_hypothesis_id") == "hypothesis:docling"
    assert first_span_meta.get("winner_source") == "docling"
    assert any("table-like region flattened" in flag.message for flag in parsed.review_flags)


def test_pdf_text_winner_provenance_cannot_be_overwritten_by_block_metadata(monkeypatch) -> None:
    dummy_hypothesis = PdfParseHypothesis(
        hypothesis_id="hypothesis:docling",
        source="docling",
        page_blocks=(LayoutBlockCandidate("dummy", 0, None, "dummy", "paragraph", 0.6, "docling"),),
        table_regions=(),
        confidence=0.6,
        metadata={"degraded": False},
    )
    arbitration = PageArbitrationResult(
        selected_blocks=(
            LayoutBlockCandidate(
                "b1",
                0,
                None,
                "Scope",
                "heading",
                0.9,
                "docling",
                {"provider": "docling", "winner_source": "bad_override", "winner_hypothesis_id": "bad_id"},
            ),
        ),
        selected_tables=(),
        hypothesis_scores={"hypothesis:docling": 220.0},
        metadata={"winner": "docling", "winner_hypothesis_id": "hypothesis:docling"},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_text.text_hypotheses", lambda **_kwargs: (dummy_hypothesis,))
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_text.arbitrate_hypotheses", lambda _hypotheses: arbitration)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="doc_pdf_text_docling_002",
        filename="memo.pdf",
        mime_type="application/pdf",
        raw_text_preview="Scope",
        metadata={"native_text_ratio": 0.98},
    )
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    assert parsed.evidence_spans
    first_span_meta = parsed.evidence_spans[0].metadata
    assert first_span_meta.get("winner_hypothesis_id") == "hypothesis:docling"
    assert first_span_meta.get("winner_source") == "docling"
