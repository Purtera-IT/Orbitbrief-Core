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
    ]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_every_packet_contains_diagnostic_surface() -> None:
    text = (
        "Scope includes parser runtime.\n"
        "Deliverable includes migration runbook.\n"
        "Assumption customer provides access.\n"
        "Risk permit delay."
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packetdiag_10_001", filename="memo.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    for packet in result.packet_candidates:
        diag = packet.metadata.get("packet_diagnostic")
        assert isinstance(diag, dict)
        assert diag.get("anchor", {}).get("reason_codes")
        assert isinstance(diag.get("included"), list)
        assert isinstance(diag.get("excluded"), list)
        assert isinstance(diag.get("score_contributions"), list)


def test_packet_diagnostic_scores_are_explainable() -> None:
    text = "Deliverable by Friday. Need access badge. Open question on site count."
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packetdiag_10_002", filename="notes.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    diag = result.packet_candidates[0].metadata["packet_diagnostic"]
    components = {item["component"] for item in diag["score_contributions"]}
    assert "anchor_strength" in components
    assert "support_density" in components
