from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.adapters.pdf_common import (
    LayoutBlockCandidate,
    PdfParseHypothesis,
    TableRegionCandidate,
    ocr_hypotheses,
)
from orbitbrief_core.parser.adapters.pdf_ocr import PdfOcrAdapter
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import ContainerType, DiscourseType


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [{"modality": "pdf_ocr", "parser_profile_id": "parser:professional_services_text:pdf_ocr"}]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _parse_plan_stub() -> ParsePlan:
    return ParsePlan(
        doc_id="ocr_doc_001",
        container_type=ContainerType.PDF,
        discourse_type=DiscourseType.PROJECT_MEMO,
        parser_profile_id="parser:professional_services_text:pdf_ocr",
        adapter_chain=("pdf_ocr",),
        strategy_chain=("project_memo",),
        quality_mode="balanced",
        authority_mode="default",
        packet_policy="default",
        routing_confidence=0.62,
        route_scores=(),
        route_evidence=(),
        metadata={"modality": "pdf_ocr"},
    )


def test_pdf_ocr_lane_propagates_provenance_and_confidence(monkeypatch) -> None:
    winner = PdfParseHypothesis(
        hypothesis_id="hypothesis:paddleocr_vl",
        source="paddleocr_vl",
        page_blocks=(
            LayoutBlockCandidate(
                "ocr_block_1",
                0,
                (0.0, 10.0, 120.0, 30.0),
                "Scope",
                "heading",
                0.82,
                "paddleocr_vl",
                {"winner_source": "paddleocr_vl", "winner_hypothesis_id": "hypothesis:paddleocr_vl"},
            ),
            LayoutBlockCandidate(
                "ocr_block_2",
                0,
                (0.0, 40.0, 320.0, 80.0),
                "Install core router.",
                "paragraph",
                0.72,
                "paddleocr_vl",
                {"winner_source": "paddleocr_vl", "winner_hypothesis_id": "hypothesis:paddleocr_vl"},
            ),
            LayoutBlockCandidate(
                "ocr_block_3",
                0,
                (0.0, 90.0, 320.0, 130.0),
                "Site | Qty",
                "table",
                0.63,
                "paddleocr_vl",
                {"winner_source": "paddleocr_vl", "winner_hypothesis_id": "hypothesis:paddleocr_vl"},
            ),
        ),
        table_regions=(TableRegionCandidate("ocr_table_1", 0, None, "Site | Qty", 0.63, "paddleocr_vl"),),
        confidence=0.72,
        metadata={"degraded": False},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_ocr.ocr_hypotheses", lambda **_kwargs: (winner,))

    adapter = PdfOcrAdapter()
    result = adapter.parse(
        router_input=RouterInput(doc_id="ocr_doc_001", filename="scan.pdf", mime_type="application/pdf", raw_text_preview=""),
        parse_plan=_parse_plan_stub(),
        compiled_pack=_compiled_pack_stub(),
    )

    assert result.evidence_spans
    first_meta = result.evidence_spans[0].metadata
    assert first_meta.get("winner_hypothesis_id") == "hypothesis:paddleocr_vl"
    assert first_meta.get("winner_source") == "paddleocr_vl"
    assert first_meta.get("role_confidence") is not None
    assert any("table OCR parser" in flag.message for flag in result.review_flags)


def test_pdf_ocr_lane_emits_uncertainty_flags(monkeypatch) -> None:
    weak = PdfParseHypothesis(
        hypothesis_id="hypothesis:tesseract",
        source="tesseract",
        page_blocks=(
            LayoutBlockCandidate("w1", 0, None, "Sc0pe ???", "paragraph", 0.35, "tesseract"),
            LayoutBlockCandidate("w2", 0, None, "Ln3 2", "paragraph", 0.31, "tesseract"),
        ),
        table_regions=(),
        confidence=0.33,
        metadata={"degraded": True},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_ocr.ocr_hypotheses", lambda **_kwargs: (weak,))

    adapter = PdfOcrAdapter()
    result = adapter.parse(
        router_input=RouterInput(doc_id="ocr_doc_002", filename="scan.pdf", mime_type="application/pdf", raw_text_preview=""),
        parse_plan=_parse_plan_stub(),
        compiled_pack=_compiled_pack_stub(),
    )
    messages = [flag.message for flag in result.review_flags]
    assert any("low_confidence_ocr" in message for message in messages)
    assert any("weak_ocr" in message for message in messages)


def test_ocr_hypotheses_fallback_when_primary_providers_missing(monkeypatch) -> None:
    fitz = PdfParseHypothesis(
        hypothesis_id="hypothesis:fitz",
        source="fitz",
        page_blocks=(LayoutBlockCandidate("f1", 0, None, "fallback", "paragraph", 0.6, "fitz"),),
        table_regions=(),
        confidence=0.6,
        metadata={},
    )
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common.extract_paddleocr_vl_pdf_hypothesis", lambda **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common.extract_pp_structure_pdf_hypothesis", lambda **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._mineru_hypothesis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common.extract_tesseract_pdf_hypothesis", lambda **_kwargs: None)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.pdf_common._fitz_text_hypothesis", lambda *_args, **_kwargs: fitz)

    hypotheses = ocr_hypotheses()
    assert len(hypotheses) == 1
    assert hypotheses[0].source == "fitz"
