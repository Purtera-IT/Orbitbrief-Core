from pathlib import Path

from orbitbrief_core.runtime_spine.heads import complexity_head, integrity_head, modality_head, review_calibrator, role_head
from orbitbrief_core.runtime_spine.file_utils import synthetic_minimal_pdf


def test_integrity_head_detects_missing_file(tmp_path: Path):
    result = integrity_head(tmp_path / "missing.txt")
    assert result["status"] == "failed"
    assert result["review_flags"]


def test_modality_head_resolves_supported_modalities(tmp_path: Path):
    txt = tmp_path / "meeting_transcript.txt"
    txt.write_text("hello")
    xlsx = tmp_path / "site_roster.xlsx"
    xlsx.write_text("placeholder")
    pdf = tmp_path / "drawing_packet.pdf"
    pdf.write_bytes(synthetic_minimal_pdf("Drawing Title"))
    assert modality_head(txt)["modality"] == "txt"
    assert modality_head(xlsx)["modality"] == "xlsx"
    assert modality_head(pdf)["modality"] == "pdf"


def test_role_head_routes_synthetic_examples(tmp_path: Path):
    transcript = tmp_path / "meeting_transcript.txt"
    transcript.write_text("Project summary")
    roster = tmp_path / "site_roster.csv"
    roster.write_text("site,address\nA,123 Main")
    drawing = tmp_path / "drawing_packet.pdf"
    drawing.write_bytes(synthetic_minimal_pdf("Drawing Packet Rev A"))
    assert role_head(transcript, "txt")["role_id"] == "transcript_or_notes"
    assert role_head(roster, "csv")["role_id"] == "site_roster_spreadsheet"
    assert role_head(drawing, "pdf")["role_id"] == "drawing_packet"


def test_role_head_normalizes_esx_and_zip_modalities(tmp_path: Path):
    esx = tmp_path / "wireless_survey_packet.esx"
    esx.write_text("placeholder")
    zipped = tmp_path / "wireless_survey_packet.zip"
    zipped.write_text("placeholder")
    assert role_head(esx, "esx")["role_id"] == "wireless_survey_packet"
    assert role_head(zipped, "zip")["role_id"] == "wireless_survey_packet"


def test_role_head_uses_role_token_hint_for_active_roles(tmp_path: Path):
    camera = tmp_path / "camera_schedule_surveillance.csv"
    camera.write_text("placeholder")
    bom = tmp_path / "bom_equipment_schedule.xlsx"
    bom.write_text("placeholder")
    assert role_head(camera, "csv")["role_id"] == "camera_schedule_surveillance"
    assert role_head(bom, "xlsx")["role_id"] == "bom_equipment_schedule"


def test_complexity_head_respects_role_policy(tmp_path: Path):
    drawing = tmp_path / "drawing_packet.pdf"
    drawing.write_bytes(synthetic_minimal_pdf("Drawing Packet"))
    result = complexity_head(drawing, "drawing_packet", "pdf")
    assert result["needs_32b_policy"] is True
    assert result["review_flags"]


def test_review_calibrator_prefers_32b_then_human():
    decision = review_calibrator(
        {"status": "ok", "review_flags": []},
        {"status": "implemented"},
        {"needs_32b_policy": True},
        [],
    )
    assert decision["decision"] == "needs_32b"
