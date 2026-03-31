from orbitbrief_core.runtime_spine.config import (
    executable_pre_schema_ref,
    load_injection_registry,
    load_role_registry,
    matrix_rows_for_role,
    post_schema_ref,
    role_runtime_status,
    schema_entry,
)


def test_implemented_roles_exist_in_stage1_registry():
    roles = load_role_registry()
    injections = load_injection_registry()
    for role_id in ("transcript_or_notes", "site_roster_spreadsheet", "drawing_packet"):
        assert role_id in roles
        assert role_id in injections


def test_transcript_docx_post_alias_is_preserved():
    row = next(row for row in matrix_rows_for_role("transcript_or_notes") if row["modality"] == "DOCX")
    assert row["post_source_ref"] == "transcript_or_notes.docx.post.alias"
    alias_entry = schema_entry("transcript_or_notes.docx.post.alias")
    assert alias_entry["aliased_to"] == "professional_services_post_orbitbrief_pasted_notes_v3"


def test_schema_refs_resolve_for_runtime_roles():
    assert executable_pre_schema_ref("transcript_or_notes", "TXT") == "transcript_or_notes.txt.pre"
    assert post_schema_ref("site_roster_spreadsheet", "XLSX") == "site_roster_spreadsheet.xlsx.post"
    assert executable_pre_schema_ref("drawing_packet", "PDF") == "drawing_packet.pdf.pre"


def test_door_schedule_remains_parked():
    assert role_runtime_status("door_schedule_access_control") == "parked"
