from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import ParseRuntimeResult, parse_and_packetize, parse_artifact


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


def test_parse_artifact_runtime_spine_returns_graph_backed_parse() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Scope: managed services\nAssumption: customer provides access.\nDeliverable: migration report."
    router_input = RouterInput(
        doc_id="spine_doc_001",
        filename="memo.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    document_parse = parse_artifact(router_input=router_input, compiled_pack=compiled_pack)
    assert len(document_parse.evidence_spans) >= 1
    assert len(document_parse.evidence_graph.edges) >= 1
    assert len(document_parse.section_tree.nodes) >= 1


def test_parse_and_packetize_emits_packets_and_diagnostics() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nTo: team@example.com\nSubject: Scope and deliverables\n\n"
        "Scope includes parser runtime delivery.\n"
        "Assumption: customer responsibilities include access.\n"
        "Open question: what is final site count?\n"
    )
    router_input = RouterInput(
        doc_id="spine_doc_002",
        filename="thread.eml",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_and_packetize(router_input=router_input, compiled_pack=compiled_pack)
    assert isinstance(result, ParseRuntimeResult)
    assert len(result.packet_candidates) >= 1
    assert any(diag == "phase:packetizer" for diag in result.diagnostics)
    packet_families = {packet.metadata.get("packet_family") for packet in result.packet_candidates}
    assert "scope_packet" in packet_families or "deliverable_packet" in packet_families
