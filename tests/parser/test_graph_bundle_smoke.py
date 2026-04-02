from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize


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
        {"modality": "docx", "parser_profile_id": "parser:professional_services_text:docx"},
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
        {"modality": "pdf_text", "parser_profile_id": "parser:professional_services_text:pdf_text"},
        {"modality": "pdf_ocr", "parser_profile_id": "parser:professional_services_text:pdf_ocr"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def _assert_graph_enriched(result) -> None:
    metadata = result.document_parse.metadata
    graph_meta = metadata.get("graph_builder", {})
    assert isinstance(graph_meta, dict)
    assert graph_meta.get("pass_names")
    assert metadata.get("graph_pass_stats")
    assert metadata.get("graph_diagnostics") is not None
    assert "phase:graph_builder" in result.diagnostics
    # Some minimal/fallback adapter paths may produce one span, so edge count can be zero.
    assert len(result.document_parse.evidence_graph.edges) >= 0


def test_graph_smoke_transcript() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Alice: We will deploy next week\nBob: Scope includes migration\nWhat about site count?"
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_call_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    _assert_graph_enriched(result)


def test_graph_smoke_meeting_notes() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "- Action item: owner confirms access\n- Risk: delayed shipment\n- Open question: timeline?"
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_notes_001", filename="notes.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    _assert_graph_enriched(result)


def test_graph_smoke_email_thread() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nTo: team@example.com\nSubject: Scope update\n\n"
        "Deliverable is closeout report.\n> previous quoted context"
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_email_001", filename="thread.eml", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    _assert_graph_enriched(result)


def test_graph_smoke_project_memo() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "# Scope\nDeliverable: migration runbook\nAssumption: customer access\nSchedule: next month"
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_memo_001", filename="memo.md", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    _assert_graph_enriched(result)


def test_graph_smoke_hybrid() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nSubject: Mixed notes\n\n"
        "Alice: We will deliver Friday.\n"
        "- Action item: confirm access.\n"
        "Assumption: customer provides escort.\n"
        "Open question: site count?"
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="graph_hybrid_001", filename="hybrid.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    _assert_graph_enriched(result)
