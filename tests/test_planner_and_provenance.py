from pathlib import Path

from orbitbrief_core.runtime_spine.pipeline import run_pipeline


def test_pipeline_smoke_emits_pre_draft_and_provenance(tmp_path: Path):
    path = tmp_path / "meeting_transcript.txt"
    path.write_text(
        "Project summary: Multi-site refresh.\n"
        "Assumption: customer provides rack space.\n"
        "Exclusion: carrier turn-up by others.\n"
        "Open question: confirm after-hours window?\n"
        "Install 3 sites.\n"
    )
    result = run_pipeline(path)
    assert result["planner_output"].canonical_pre_draft
    assert result["provenance"]["records"]
    assert result["provenance"]["events"]
    assert result["review_decision"]["decision"] in {"auto_accept", "needs_32b", "needs_human_review"}


def test_pipeline_exits_cleanly_for_not_implemented_role(tmp_path: Path):
    path = tmp_path / "audit_site_review.pdf"
    path.write_bytes(b"%PDF-1.4\n% minimal placeholder")
    result = run_pipeline(path)
    assert result["role_result"]["role_id"] == "audit_site_review"
    assert result["role_result"]["status"] == "not_implemented"
    assert "ingested" in result
    assert result["ingested"]["review_flags"]
    assert result["ingested"]["role_graph"].summary.startswith("Intake-only fallback executed")
    assert result["review_decision"]["decision"] == "needs_human_review"
