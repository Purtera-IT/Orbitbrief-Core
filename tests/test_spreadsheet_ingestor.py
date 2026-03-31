from pathlib import Path

from orbitbrief_core.runtime_spine.ingestors import ingest_site_roster_spreadsheet

from .helpers import write_xlsx


def test_csv_roster_ingestion_produces_table_and_rows(tmp_path: Path):
    path = tmp_path / "site_roster.csv"
    path.write_text(
        "Site Name,Address,AP Count,Notes,Go Live\n"
        "Austin,123 Main,12,Install switches,2026-05-01\n"
        "Dallas,456 Oak,8,Access requires badge,2026-05-02\n"
    )
    result = ingest_site_roster_spreadsheet(path, "csv")
    assert result["role_graph"].role_id == "site_roster_spreadsheet"
    assert any(obj.object_type == "TableObject" for obj in result["evidence_objects"])
    assert any(obj.object_type == "RowObject" for obj in result["evidence_objects"])
    assert any(claim.field_name == "site_count" for claim in result["field_claims"])
    assert any(claim.field_name == "site_roster_rows" for claim in result["field_claims"])
    assert result["mapping_decisions"]


def test_xlsx_roster_ingestion_preserves_sheet_provenance(tmp_path: Path):
    path = tmp_path / "site_roster.xlsx"
    write_xlsx(
        path,
        ["Site ID", "City / State / Zip", "Notes", "Total Sites"],
        [["A1", "Austin, TX 78701", "Assumption: customer provides access", "2"], ["D2", "Dallas, TX 75001", "Question: final schedule?", "2"]],
    )
    result = ingest_site_roster_spreadsheet(path, "xlsx")
    table = next(obj for obj in result["evidence_objects"] if obj.object_type == "TableObject")
    assert table.page_ref_or_sheet_ref.name == "Sites"
    assert any(claim.field_name == "location_details" for claim in result["field_claims"])
    assert any(decision.target_path == "site_count" for decision in result["mapping_decisions"])


def test_xls_is_explicitly_routed_to_review(tmp_path: Path):
    path = tmp_path / "site_roster.xls"
    path.write_text("legacy xls placeholder")
    result = ingest_site_roster_spreadsheet(path, "xls")
    assert result["review_flags"]
    assert result["review_flags"][0].code == "xls_not_yet_supported"
