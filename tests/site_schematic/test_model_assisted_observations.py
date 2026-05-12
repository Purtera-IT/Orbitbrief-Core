from __future__ import annotations

from pathlib import Path

import fitz

from orbitbrief_core.parser.adapters.providers.base import ProviderLayoutBlock, ProviderPdfHypothesis, ProviderTableRegion
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.classification.sheet_type import classify_sheet
from orbitbrief_core.parser.site_schematic.core import build_page_decomposition
from orbitbrief_core.parser.site_schematic.observations import build_site_schematic_page_observations


def _make_simple_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((72, 72), "T900 ENLARGED EQUIPMENT ROOM LAYOUTS", fontsize=14)
    page.insert_text((72, 120), "DETAIL A - MDF RACK ELEVATION", fontsize=12)
    page.insert_text((72, 180), "T906 | INSTALLATION DETAILS", fontsize=11)
    page.draw_line((600, 50), (600, 560))
    doc.save(path)
    doc.close()


def test_pdf_native_observations_emit_words_blocks_and_vectors(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _make_simple_pdf(pdf_path)
    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="obs-native",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {"enabled": True},
            "pdf_backbone": {"enabled": False, "provider": "docling"},
        },
    )
    assert len(observations) == 1
    assert observations[0].source_mode == "pdf_native"
    assert diagnostics["used"] is True
    assert diagnostics["winner"] == "pdf_native"
    assert observations[0].words
    assert observations[0].layout_blocks
    assert observations[0].vector_items


def test_docling_merge_enriches_native_observations(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _make_simple_pdf(pdf_path)

    def _docling(*_args, **_kwargs):
        return ProviderPdfHypothesis(
            hypothesis_id="hypothesis:docling",
            source="docling",
            page_blocks=(
                ProviderLayoutBlock(
                    block_id="d:1",
                    page_index=0,
                    bbox=(0.0, 0.0, 100.0, 20.0),
                    text="T900 ENLARGED EQUIPMENT ROOM LAYOUTS",
                    role="heading",
                    confidence=0.9,
                    source="docling",
                    metadata={},
                ),
                ProviderLayoutBlock(
                    block_id="d:2",
                    page_index=0,
                    bbox=(0.0, 40.0, 300.0, 110.0),
                    text="DETAIL A - MDF RACK ELEVATION WITH PATCH PANEL",
                    role="paragraph",
                    confidence=0.88,
                    source="docling",
                    metadata={},
                ),
                ProviderLayoutBlock(
                    block_id="d:3",
                    page_index=0,
                    bbox=(0.0, 120.0, 300.0, 200.0),
                    text="GENERAL NOTES: 1. BOND TO TMGB",
                    role="paragraph",
                    confidence=0.85,
                    source="docling",
                    metadata={},
                ),
            ),
            table_regions=(
                ProviderTableRegion(
                    region_id="t:1",
                    page_index=0,
                    bbox=(0.0, 220.0, 300.0, 280.0),
                    text="T906 | INSTALLATION DETAILS",
                    confidence=0.84,
                    source="docling",
                    metadata={},
                ),
            ),
            confidence=0.9,
            metadata={"degraded": False},
        )

    monkeypatch.setattr("orbitbrief_core.parser.site_schematic.observations.extract_docling_pdf_hypothesis", _docling)

    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="obs-native-docling",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {"enabled": True, "docling_merge_enabled": True},
            "pdf_backbone": {"enabled": True, "provider": "docling"},
        },
        sheet_types=["legend_symbol"],
    )
    assert diagnostics["used"] is True
    assert diagnostics["winner"] == "pdf_native_docling"
    assert observations[0].layout_blocks
    assert observations[0].table_blocks
    assert observations[0].provider == "fitz+docling"
    assert observations[0].source_mode == "pdf_native_docling"

    classification = classify_sheet(observations[0].page_text)
    regions, detail_regions, subregions, pseudo_pages = build_page_decomposition(
        page_index=1,
        text=observations[0].page_text,
        classification=classification,
        page_observation=observations[0],
    )
    assert any(region.metadata.get("provider") in {"fitz+docling", "docling", "fitz"} for region in regions)
    assert any("provider" in detail.metadata for detail in detail_regions)
    assert subregions
    assert pseudo_pages
