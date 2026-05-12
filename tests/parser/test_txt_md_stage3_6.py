from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.adapters.text_common import segment_text
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import route_and_parse


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [
        {"modality": "txt", "parser_profile_id": "parser:professional_services_text:txt"},
        {"modality": "md", "parser_profile_id": "parser:professional_services_text:md"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_txt_emits_structural_ambiguity_hooks() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Project Notes:\nCapture site constraints.\n\n- Primary task\n  - Sub task"
    router_input = RouterInput(
        doc_id="doc_txt_3_6_001",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    paragraph_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") in {"paragraph", "action_item"}]
    assert paragraph_spans
    assert "ambiguous_heading_candidate" in paragraph_spans[0].metadata.get("ambiguity_tags", [])
    assert paragraph_spans[0].metadata.get("candidate_heading_strength") is not None

    bullet_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") == "bullet"]
    assert bullet_spans
    assert "list_kind" in bullet_spans[0].metadata


def test_markdown_preserves_structure_for_heading_list_quote_and_code() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "# Scope\n- Install rack\n> Prior context\n```python\nprint('x')\n```"
    router_input = RouterInput(
        doc_id="doc_md_3_6_001",
        filename="memo.md",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    assert any(node.title == "Scope" for node in parsed.section_tree.nodes)
    kinds = {str(span.metadata.get("kind")) for span in parsed.evidence_spans}
    assert "heading" in kinds
    assert "bullet" in kinds
    assert "blockquote" in kinds
    assert "code_fence" in kinds


def test_markdown_paragraph_emits_light_ambiguity_hooks_when_heading_like() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "# Scope\nProject Notes:\nNeed wiring map."
    router_input = RouterInput(
        doc_id="doc_md_3_6_002",
        filename="memo.md",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    paragraph_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") == "paragraph"]
    assert paragraph_spans
    assert "ambiguous_heading_candidate" in paragraph_spans[0].metadata.get("ambiguity_tags", [])
    assert paragraph_spans[0].metadata.get("candidate_heading_strength", 0.0) >= 0.58


def test_segment_text_sets_candidate_neighborhood_ids() -> None:
    result = segment_text("First paragraph.\n\nSecond paragraph.\n\nThird paragraph.")
    assert len(result.paragraphs) == 3
    assert result.paragraphs[0].metadata.get("candidate_neighborhood_ids") == [result.paragraphs[1].paragraph_id]
    assert result.paragraphs[1].metadata.get("candidate_neighborhood_ids") == [
        result.paragraphs[0].paragraph_id,
        result.paragraphs[2].paragraph_id,
    ]
