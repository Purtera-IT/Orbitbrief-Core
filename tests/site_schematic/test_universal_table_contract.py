from __future__ import annotations

from .gold_eval import LOW_VOLTAGE_PDF_FIXTURE, WIRELESS_PDF_FIXTURE, build_pdf_bundle
from .universal_table_contract_eval import run_universal_table_contract_eval


def test_universal_table_spine_emits_tables_with_rows_and_cells() -> None:
    bundle = build_pdf_bundle(WIRELESS_PDF_FIXTURE)
    assert bundle.universal_tables
    first_table = bundle.universal_tables[0]
    assert first_table.table_id
    assert first_table.rows
    assert first_table.rows[0].cells
    assert first_table.rows[0].cells[0].source_token_ids


def test_table_derived_semantics_have_lineage_refs() -> None:
    bundle = build_pdf_bundle(LOW_VOLTAGE_PDF_FIXTURE)
    assert bundle.semantic_lineage_refs
    assert any(ref.semantic_object_type in {"drawing_index_row", "legend_entry", "abbreviation_entry", "outlet_definition"} for ref in bundle.semantic_lineage_refs)
    assert all(ref.source_table_id and ref.source_row_id for ref in bundle.semantic_lineage_refs)


def test_universal_table_contract_eval_reports_hard_pages() -> None:
    report = run_universal_table_contract_eval()
    assert report["status"] in {"perfect", "not_perfect"}
    page_ids = {row["gold_page_id"] for row in report["page_results"]}
    assert {
        "wireless_tc001_page1",
        "southern_t000_page1",
        "southern_t001_page2",
        "southern_t002_page3",
        "southern_t900_page12",
        "southern_t905_page17",
    } <= page_ids
    metrics = report["metrics"]
    assert 0.0 <= metrics["required_table_kind_coverage"] <= 1.0
    assert 0.0 <= metrics["bbox_presence_rate"] <= 1.0
    assert 0.0 <= metrics["semantic_row_reference_rate"] <= 1.0
