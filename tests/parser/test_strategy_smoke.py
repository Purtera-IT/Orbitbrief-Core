from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import ParserRouter, RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize, parse_with_plan
from orbitbrief_core.parser.strategies.call_transcript import CallTranscriptStrategy
from orbitbrief_core.parser.strategies.email_thread import EmailThreadStrategy
from orbitbrief_core.parser.strategies.hybrid import HybridStrategy
from orbitbrief_core.parser.strategies.meeting_notes import MeetingNotesStrategy
from orbitbrief_core.parser.strategies.project_memo import ProjectMemoStrategy


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


def _base_parse(compiled_pack: _CompiledPackStub, *, doc_id: str, filename: str, text: str):
    router = ParserRouter(compiled_pack)
    router_input = RouterInput(doc_id=doc_id, filename=filename, raw_text_preview=text, metadata={"raw_text": text})
    parse_plan = router.route(router_input)
    return parse_plan, parse_with_plan(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)


def test_call_transcript_strategy_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    parse_plan, base_parse = _base_parse(
        compiled_pack,
        doc_id="strategy_call_001",
        filename="call.txt",
        text="Alice: We will finalize scope\nNeed to confirm schedule?",
    )
    enriched = CallTranscriptStrategy().apply(document_parse=base_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    assert "call_transcript" in enriched.metadata.get("strategy_trace", [])
    assert any("call_transcript" in diag for diag in enriched.metadata.get("strategy_diagnostics", []))


def test_meeting_notes_strategy_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    parse_plan, base_parse = _base_parse(
        compiled_pack,
        doc_id="strategy_notes_001",
        filename="notes.txt",
        text="- Action item: owner to confirm access\n- Risk: delayed shipment\n- Open question: site count?",
    )
    enriched = MeetingNotesStrategy().apply(document_parse=base_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    assert "meeting_notes" in enriched.metadata.get("strategy_trace", [])
    assert any(span.metadata.get("notes_zone") for span in enriched.evidence_spans)


def test_email_thread_strategy_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nTo: team@example.com\nSubject: status\n\nCurrent update line.\n"
        "> quoted old line"
    )
    parse_plan, base_parse = _base_parse(compiled_pack, doc_id="strategy_email_001", filename="thread.eml", text=text)
    enriched = EmailThreadStrategy().apply(document_parse=base_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    assert "email_thread" in enriched.metadata.get("strategy_trace", [])
    assert any(span.metadata.get("thread_zone") for span in enriched.evidence_spans)


def test_project_memo_strategy_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    parse_plan, base_parse = _base_parse(
        compiled_pack,
        doc_id="strategy_memo_001",
        filename="memo.md",
        text="# Scope\nDeliverable: migration runbook\nAssumption: customer access",
    )
    enriched = ProjectMemoStrategy().apply(document_parse=base_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    assert "project_memo" in enriched.metadata.get("strategy_trace", [])
    assert any(span.metadata.get("memo_zone") for span in enriched.evidence_spans)


def test_hybrid_strategy_smoke() -> None:
    compiled_pack = _compiled_pack_stub()
    parse_plan, base_parse = _base_parse(
        compiled_pack,
        doc_id="strategy_hybrid_001",
        filename="hybrid.txt",
        text=(
            "From: lead@example.com\nSubject: mixed\n\n"
            "Alice: We will deliver by Friday.\n"
            "Assumption: customer provides access.\n"
            "Open question: site count?"
        ),
    )
    enriched = HybridStrategy().apply(document_parse=base_parse, parse_plan=parse_plan, compiled_pack=compiled_pack)
    assert "hybrid" in enriched.metadata.get("strategy_trace", [])
    assert "hybrid_mix" in enriched.metadata


def test_runtime_spine_enriches_vs_pre_strategy() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Alice: scope includes deployment\nBob: deliverable is closeout report\nNeed schedule confirmation?"
    router = ParserRouter(compiled_pack)
    router_input = RouterInput(doc_id="strategy_e2e_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text})
    parse_plan = router.route(router_input)
    pre = parse_with_plan(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
    post = parse_and_packetize(router_input=router_input, compiled_pack=compiled_pack).document_parse
    assert len(post.metadata.get("strategy_trace", [])) >= 1
    assert len(post.evidence_graph.edges) >= len(pre.evidence_graph.edges)
