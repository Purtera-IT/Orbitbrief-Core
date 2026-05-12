from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.symbols.export import (
    build_symbol_export_sidecar_rows,
    export_symbol_candidate_crops,
)


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 1>
TC001 TELECOMM SYMBOL LIST
AP WIRELESS ACCESS POINT OUTLET
3. PROVIDE CABLE SLACK FOR WIRELESS ACCESS POINTS. TERMINATE WAP CABLES ON DEDICATED PATCH PANEL.
""".strip()


def _write_minimal_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def test_symbol_export_sidecar_rows_include_contract_fields() -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="symbol-export",
            filename="symbol-export.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    rows = build_symbol_export_sidecar_rows(bundle=bundle, packet_id="packet-symbol-export")
    assert rows
    first = rows[0]
    assert first["packet_id"] == "packet-symbol-export"
    assert "candidate_id" in first
    assert "page_index" in first
    assert "nearby_note_clauses" in first
    assert "nearby_legend_texts" in first
    assert "vocabulary_primary_class_id" in first
    assert "vocabulary_tier1" in first
    assert "vocabulary_tier2" in first
    assert "detector_class_id" in first
    assert "detector_selected_for_first_pass" in first


def test_symbol_export_crops_writes_metadata_even_when_render_skips(tmp_path: Path) -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="symbol-export-crops",
            filename="symbol-export-crops.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    pdf_path = tmp_path / "blank.pdf"
    _write_minimal_pdf(pdf_path)
    report = export_symbol_candidate_crops(
        bundle=bundle,
        pdf_path=pdf_path,
        output_dir=tmp_path / "exports",
        packet_id="packet-crops",
    )
    metadata_path = Path(report["metadata_path"])
    assert metadata_path.exists()
    lines = metadata_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    assert report["candidate_count"] == len(bundle.symbol_candidate_inputs)
