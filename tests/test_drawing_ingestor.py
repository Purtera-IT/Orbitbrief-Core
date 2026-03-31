from pathlib import Path

from orbitbrief_core.runtime_spine.ingestors import ingest_drawing_packet

from .helpers import write_pdf


def test_drawing_packet_ingestion_creates_sheet_lane(tmp_path: Path):
    path = tmp_path / "drawing_packet.pdf"
    write_pdf(path, "Drawing Title\nRev A\nRoom 101\nDeliverable as-built\nTest requirement")
    result = ingest_drawing_packet(path, "pdf")
    assert result["role_graph"].role_id == "drawing_packet"
    assert any(obj.object_type == "SheetObject" for obj in result["evidence_objects"])
    assert any(obj.object_type == "ImageCrop" for obj in result["evidence_objects"])
    assert any(flag.requires_32b for flag in result["review_flags"])


def test_drawing_packet_claims_are_safe_and_scoped(tmp_path: Path):
    path = tmp_path / "drawing_packet.pdf"
    write_pdf(path, "Site Austin\nRoom 101\nAccess badge required\n3 racks\nOpen question?")
    result = ingest_drawing_packet(path, "pdf")
    field_names = {claim.field_name for claim in result["field_claims"]}
    assert field_names.intersection({"location_details", "access_constraints", "known_quantities", "open_questions"})
