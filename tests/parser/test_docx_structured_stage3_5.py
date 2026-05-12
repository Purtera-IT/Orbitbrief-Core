from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.adapters.docx import DocxBlock, DocxAdapter
from orbitbrief_core.parser.adapters.docx_common import StructuredDocxBlock, StructuredDocxHypothesis
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
    rows = [{"modality": "docx", "parser_profile_id": "parser:professional_services_text:docx"}]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_docx_reconciliation_recovers_heading_and_list_nesting(monkeypatch) -> None:
    deterministic_blocks = (
        DocxBlock("paragraph", "Assumptions", "Normal", None, {"is_list": False, "list_level": None}),
        DocxBlock("bullet", "Install rack", "List Paragraph", None, {"is_list": True, "list_level": 1}),
    )
    alternate = StructuredDocxHypothesis(
        hypothesis_id="hypothesis:docx_structured",
        source="alternate_structured",
        blocks=(
            StructuredDocxBlock(
                block_id="alt:0001",
                text="Assumptions",
                role="heading",
                style_name="Heading 2",
                heading_level=2,
                list_level=None,
                table_group_id=None,
                section_hint="assumptions",
                confidence=0.88,
                source="alternate_structured",
                metadata={},
            ),
            StructuredDocxBlock(
                block_id="alt:0002",
                text="Install rack",
                role="bullet",
                style_name="List Paragraph",
                heading_level=None,
                list_level=3,
                table_group_id=None,
                section_hint=None,
                confidence=0.83,
                source="alternate_structured",
                metadata={},
            ),
        ),
        confidence=0.84,
        metadata={},
    )
    monkeypatch.setattr(DocxAdapter, "_extract_blocks", lambda _self, _router_input: deterministic_blocks)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.docx.extract_docx_structured_hypothesis", lambda **_kwargs: alternate)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(doc_id="docx_stage3_5_001", filename="memo.docx", raw_text_preview="Assumptions\n- Install rack", metadata={"raw_text": "Assumptions\n- Install rack"})
    plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    assert plan.adapter_chain[0] == "docx"
    assert any(node.title == "Assumptions" for node in parsed.section_tree.nodes)
    bullet_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") == "bullet"]
    assert bullet_spans
    assert bullet_spans[0].metadata.get("list_level") == 3
    assert "list_level_reconciled" in bullet_spans[0].metadata.get("reconciliation_reason_codes", [])


def test_docx_reconciliation_updates_table_association_and_fallback(monkeypatch) -> None:
    deterministic_blocks = (
        DocxBlock("table_row", "Site A | 4", "table", None, {"row_index": 0, "table_group_id": "table:ooxml:0000"}),
    )
    alternate = StructuredDocxHypothesis(
        hypothesis_id="hypothesis:docx_structured",
        source="alternate_structured",
        blocks=(
            StructuredDocxBlock(
                block_id="alt:table1",
                text="Site A | 4",
                role="table_row",
                style_name="table",
                heading_level=None,
                list_level=None,
                table_group_id="table:alternate:0011",
                section_hint=None,
                confidence=0.80,
                source="alternate_structured",
                metadata={},
            ),
        ),
        confidence=0.8,
        metadata={},
    )
    monkeypatch.setattr(DocxAdapter, "_extract_blocks", lambda _self, _router_input: deterministic_blocks)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.docx.extract_docx_structured_hypothesis", lambda **_kwargs: alternate)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(doc_id="docx_stage3_5_002", filename="memo.docx", raw_text_preview="Site A | 4", metadata={"raw_text": "Site A | 4"})
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    table_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") == "table_row"]
    assert table_spans
    assert table_spans[0].metadata.get("table_group_id") == "table:alternate:0011"
    assert "table_association_reconciled" in table_spans[0].metadata.get("reconciliation_reason_codes", [])

    monkeypatch.setattr("orbitbrief_core.parser.adapters.docx.extract_docx_structured_hypothesis", lambda **_kwargs: None)
    _plan2, parsed2 = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)
    table_spans2 = [span for span in parsed2.evidence_spans if span.metadata.get("kind") == "table_row"]
    assert table_spans2
    assert table_spans2[0].metadata.get("winner_source") == "ooxml"


def test_docx_reconciliation_prefers_deterministic_when_provider_signal_is_weak(monkeypatch) -> None:
    deterministic_blocks = (
        DocxBlock("paragraph", "The work includes retrofitting existing racks.", "Normal", None, {"is_list": False, "list_level": None}),
        DocxBlock("bullet", "Install rack", "List Paragraph", None, {"is_list": True, "list_level": 2}),
    )
    alternate = StructuredDocxHypothesis(
        hypothesis_id="hypothesis:docx_structured",
        source="alternate_structured",
        blocks=(
            StructuredDocxBlock(
                block_id="alt:0001",
                text="The work includes retrofitting existing racks.",
                role="heading",
                style_name="Heading 2",
                heading_level=2,
                list_level=None,
                table_group_id=None,
                section_hint="scope",
                confidence=0.86,
                source="alternate_structured",
                metadata={},
            ),
            StructuredDocxBlock(
                block_id="alt:0002",
                text="Install rack",
                role="bullet",
                style_name="List Paragraph",
                heading_level=None,
                list_level=4,
                table_group_id=None,
                section_hint=None,
                confidence=0.90,
                source="alternate_structured",
                metadata={},
            ),
        ),
        confidence=0.87,
        metadata={},
    )
    monkeypatch.setattr(DocxAdapter, "_extract_blocks", lambda _self, _router_input: deterministic_blocks)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.docx.extract_docx_structured_hypothesis", lambda **_kwargs: alternate)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(
        doc_id="docx_stage3_5_003",
        filename="memo.docx",
        raw_text_preview="The work includes retrofitting existing racks.\n- Install rack",
        metadata={"raw_text": "The work includes retrofitting existing racks.\n- Install rack"},
    )
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    assert all(node.title != "The work includes retrofitting existing racks." for node in parsed.section_tree.nodes)
    bullet_spans = [span for span in parsed.evidence_spans if span.metadata.get("kind") == "bullet"]
    assert bullet_spans
    assert bullet_spans[0].metadata.get("list_level") == 2
    assert "list_level_reconciled" not in bullet_spans[0].metadata.get("reconciliation_reason_codes", [])


def test_docx_reconciliation_provenance_metadata_present_on_spans_and_sections(monkeypatch) -> None:
    deterministic_blocks = (DocxBlock("paragraph", "Scope", "Normal", None, {"is_list": False, "list_level": None}),)
    monkeypatch.setattr(DocxAdapter, "_extract_blocks", lambda _self, _router_input: deterministic_blocks)
    monkeypatch.setattr("orbitbrief_core.parser.adapters.docx.extract_docx_structured_hypothesis", lambda **_kwargs: None)

    compiled_pack = _compiled_pack_stub()
    router_input = RouterInput(doc_id="docx_stage3_5_004", filename="memo.docx", raw_text_preview="Scope", metadata={"raw_text": "Scope"})
    _plan, parsed = route_and_parse(router_input=router_input, compiled_pack=compiled_pack)

    required_keys = {
        "winner_source",
        "winner_hypothesis_id",
        "reconciled",
        "reconciliation_reason_codes",
        "competing_sources",
    }

    assert parsed.evidence_spans
    for span in parsed.evidence_spans:
        assert required_keys.issubset(set(span.metadata.keys()))

    assert parsed.section_tree.nodes
    for node in parsed.section_tree.nodes:
        assert required_keys.issubset(set(node.metadata.keys()))
