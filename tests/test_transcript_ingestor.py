from pathlib import Path

import pytest

from orbitbrief_core.runtime_spine.ingestors import ingest_transcript_or_notes

from .helpers import write_docx


@pytest.mark.parametrize(
    ("filename", "modality"),
    [
        ("meeting_transcript.txt", "txt"),
        ("meeting_notes.md", "md"),
        ("meeting_notes.docx", "docx"),
        ("email_export.txt", "email_export"),
    ],
)
def test_transcript_like_ingestion_generates_claims_and_graph(tmp_path: Path, filename: str, modality: str):
    path = tmp_path / filename
    text = """Project summary: Multi-site refresh.\nAssumption: customer provides rack space.\nExclusion: no carrier turn-up.\nOpen question: confirm after-hours window?\nInstall 3 sites.\n"""
    if modality == "docx":
        write_docx(path, text)
    else:
        path.write_text(text)
    result = ingest_transcript_or_notes(path, modality)
    assert result["role_graph"].role_id == "transcript_or_notes"
    assert result["evidence_objects"]
    assert any(claim.field_name == "project_summary" for claim in result["field_claims"])
    assert all(claim.role_id == "transcript_or_notes" for claim in result["field_claims"])


def test_transcript_docx_post_alias_is_honored(tmp_path: Path):
    path = tmp_path / "meeting_notes.docx"
    write_docx(path, "Project summary: Refresh.\nOpen question: timing?")
    result = ingest_transcript_or_notes(path, "docx")
    post_claims = [claim for claim in result["field_claims"] if claim.target_layer == "post_hint"]
    assert post_claims
    assert all(claim.schema_ref == "transcript_or_notes.docx.post.alias" for claim in post_claims)
