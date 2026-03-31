from pathlib import Path

from orbitbrief_core.runtime_spine.extractors import (
    InternalNarrativeClaim,
    build_text_narrative_extractor_prompt,
    project_to_post_hints,
    project_to_rich_txt_pre,
    project_to_slim_pre,
)
from orbitbrief_core.runtime_spine.parsers.professional_services.text_narrative import TextNarrativeParser

from .helpers import write_docx


def test_text_narrative_parser_has_frozen_io_version(tmp_path: Path):
    path = tmp_path / "meeting_notes.md"
    path.write_text("# Scope\n- Install switches\n- Validate uplinks")
    parser = TextNarrativeParser()
    parsed = parser.parse(path, "md", role_hint="transcript_or_notes")
    assert parsed.parser_id == "text_narrative_parser"
    assert parsed.parser_version == "1.0.0"
    assert parsed.metadata["io_version"] == "1.0.0"
    assert parsed.blocks
    assert any(block.block_type == "heading" for block in parsed.blocks)
    assert any(block.block_type == "list_item" for block in parsed.blocks)


def test_text_narrative_docx_adapter_yields_segments(tmp_path: Path):
    path = tmp_path / "notes.docx"
    write_docx(path, "Project summary\n- deliverables\n- assumptions")
    parsed = TextNarrativeParser().parse(path, "docx")
    assert parsed.blocks
    assert all(block.metadata.get("modality") == "docx" for block in parsed.blocks)


def test_narrative_projectors_cover_rich_slim_and_post():
    claims = [
        InternalNarrativeClaim("project_summary", "Refresh 10 sites", 0.92),
        InternalNarrativeClaim("scope_included_claim", ["Install APs"], 0.88),
        InternalNarrativeClaim("assumption_claim", ["Customer provides lift"], 0.86),
        InternalNarrativeClaim("open_question_claim", ["Confirm blackout window"], 0.71),
    ]
    rich = project_to_rich_txt_pre(claims)
    slim = project_to_slim_pre(claims)
    post = project_to_post_hints(claims)
    assert rich["project_summary"] == "Refresh 10 sites"
    assert "scope_included" in rich
    assert "known_assumptions" in slim
    assert "scope_overview" in post


def test_prompt_template_is_schema_bounded():
    prompt = build_text_narrative_extractor_prompt(
        {
            "domain_id": "professional_services",
            "role_id": "transcript_or_notes",
            "modality": "txt",
            "source_schema_ref": "professional_services_pre_orbitbrief_txt_v1",
            "allowed_fields": ["project_summary", "known_assumptions", "open_questions"],
            "allowed_field_paths": ["project_summary", "known_assumptions[]", "open_questions[]"],
            "normalized_segments": [{"segment_id": "seg_0001", "block_type": "paragraph", "text": "Assumption: customer provides racks."}],
            "retrieval_bundle": [{"family": "assumption_claim", "phrase": "customer provides"}],
        }
    )
    assert "Extract only schema-bounded claims" in prompt
    assert "allowed_fields" in prompt
