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


def _sample_result():
    compiled_pack = _compiled_pack_stub()
    text = (
        "From: lead@example.com\nTo: team@example.com\nSubject: Scope update\n\n"
        "Alice: We will deliver next week.\n"
        "Bob: Risk is permit delay.\n"
        "> previous context\n"
        "Schedule: next month."
    )
    return parse_and_packetize(
        router_input=RouterInput(doc_id="graph_stage4_1_001", filename="thread.eml", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )


def test_graph_pass_order_is_layered_and_packet_pass_last() -> None:
    result = _sample_result()
    pass_names = result.document_parse.metadata.get("graph_builder", {}).get("pass_names", [])
    assert pass_names == [
        "StructuralPass",
        "ThreadConversationPass",
        "ChronologyPass",
        "AuthorityPass",
        "SemanticCuePass",
        "PacketNeighborhoodPass",
    ]
    assert pass_names[-1] == "PacketNeighborhoodPass"


def test_graph_edges_carry_source_pass_and_reason_codes() -> None:
    result = _sample_result()
    for edge in result.document_parse.evidence_graph.edges:
        assert edge.metadata.get("source_pass")
        assert isinstance(edge.metadata.get("reason_codes"), list)
        assert edge.metadata.get("edge_family")
    for edge in result.document_parse.chronology_graph.edges:
        assert edge.metadata.get("source_pass")
        assert isinstance(edge.metadata.get("reason_codes"), list)
        assert edge.metadata.get("edge_family")
    for edge in result.document_parse.actor_graph.edges:
        assert edge.metadata.get("source_pass")
        assert isinstance(edge.metadata.get("reason_codes"), list)
        assert edge.metadata.get("edge_family")
    if result.document_parse.thread_graph is not None:
        for edge in result.document_parse.thread_graph.edges:
            assert edge.metadata.get("source_pass")
            assert isinstance(edge.metadata.get("reason_codes"), list)
            assert edge.metadata.get("edge_family")


def test_graph_has_no_duplicate_identical_edges() -> None:
    result = _sample_result()
    seen: set[tuple[str, str, str, str]] = set()
    for edge in result.document_parse.evidence_graph.edges:
        signature = (
            edge.source_span_id,
            edge.target_span_id,
            edge.relation_type.value,
            str(edge.metadata.get("edge_family", "")),
        )
        assert signature not in seen
        seen.add(signature)
