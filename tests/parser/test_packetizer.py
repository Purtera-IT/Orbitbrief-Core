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
        {"modality": "email_export", "parser_profile_id": "parser:professional_services_text:email_export"},
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_packetizer_uses_graph_backed_neighborhoods() -> None:
    text = (
        "Alice: Scope includes runtime migration.\n"
        "Alice: Deliverable is runbook and cutover checklist.\n"
        "Alice: Risk is permit delay.\n"
        "Bob: unrelated social chatter."
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packetizer_10_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    diag = result.packet_candidates[0].metadata.get("packet_diagnostic", {})
    assert diag.get("included")
    assert isinstance(diag.get("graph_edges_used"), list)


def test_packetizer_marks_uncertainty_on_weak_support() -> None:
    text = "maybe maybe maybe\nunclear ask later\nquestion?"
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packetizer_10_002", filename="notes.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    diag = result.packet_candidates[0].metadata.get("packet_diagnostic", {})
    assert "uncertainty_markers" in diag
    assert isinstance(diag["uncertainty_markers"], list)
