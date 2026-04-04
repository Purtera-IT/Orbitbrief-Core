from __future__ import annotations

from pathlib import Path

from orbitbrief_core.runtime_spine.pipeline import run_pipeline


def test_run_pipeline_returns_legacy_envelope_without_explicit_compiled_pack(tmp_path: Path) -> None:
    artifact = tmp_path / "meeting_transcript.txt"
    artifact.write_text(
        "Project summary: refresh\n"
        "Assumption: customer provides access\n"
        "Open question: final schedule?\n",
        encoding="utf-8",
    )
    result = run_pipeline(artifact)
    assert "planner_output" in result
    assert "provenance" in result
    assert "review_decision" in result
    assert "role_result" in result
    assert "ingested" in result
    assert result["role_result"]["role_id"] == "transcript_or_notes"


def test_run_pipeline_infers_audit_role_for_audit_named_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "audit_site_review.pdf"
    artifact.write_bytes(b"%PDF-1.4\n% minimal")
    result = run_pipeline(artifact)
    assert result["role_result"]["role_id"] == "audit_site_review"
    assert result["review_decision"]["decision"] in {"needs_human_review", "needs_32b", "auto_accept"}
