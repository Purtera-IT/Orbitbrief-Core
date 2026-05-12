from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.packetizer import build_packets
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize, parse_artifact


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


def _sample_result():
    text = (
        "09:00 Alice: Scope includes parser runtime delivery.\n"
        "09:02 Alice: Assumption customer provides access.\n"
        "09:04 Bob: Risk is permit delay.\n"
        "09:06 Bob: Open question on final site count?"
    )
    return parse_and_packetize(
        router_input=RouterInput(doc_id="packet_diag_5_2_001", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )


def test_packet_candidates_include_structured_packet_diagnostics() -> None:
    result = _sample_result()
    assert result.packet_candidates
    packet = result.packet_candidates[0]
    diag = packet.metadata.get("packet_diagnostic")
    assert isinstance(diag, dict)
    assert diag.get("anchor", {}).get("anchor_span_id")
    assert isinstance(diag.get("included"), list)
    assert isinstance(diag.get("excluded"), list)
    assert isinstance(diag.get("score_contributions"), list)
    assert isinstance(diag.get("graph_edges_used"), list)


def test_packet_diagnostics_capture_inclusion_exclusion_and_family_rationale() -> None:
    result = _sample_result()
    packet = result.packet_candidates[0]
    diag = packet.metadata["packet_diagnostic"]
    assert diag["family"]["assigned_family"]
    assert diag["family"]["rationale_codes"]
    assert all(entry.get("inclusion_reason_codes") for entry in diag["included"])
    if diag["excluded"]:
        assert all(entry.get("exclusion_reason_codes") for entry in diag["excluded"])


def test_packet_score_contributions_and_uncertainty_markers_exposed() -> None:
    result = _sample_result()
    packet = result.packet_candidates[0]
    diag = packet.metadata["packet_diagnostic"]
    contributions = diag["score_contributions"]
    assert contributions
    components = {item["component"] for item in contributions}
    assert "anchor_strength" in components
    assert "support_density" in components
    assert "section_cohesion" in components
    assert isinstance(diag["uncertainty_markers"], list)


def test_packet_debug_bundle_aggregation_is_structured() -> None:
    text = (
        "09:00 Alice: Scope includes parser runtime delivery.\n"
        "09:02 Alice: Deliverable is migration runbook.\n"
        "09:04 Bob: Risk is permit delay."
    )
    compiled_pack = _compiled_pack_stub()
    parsed = parse_artifact(
        router_input=RouterInput(doc_id="packet_diag_5_2_002", filename="call.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=compiled_pack,
    )
    packetizer_result = build_packets(parsed, compiled_pack=compiled_pack)
    assert packetizer_result.packet_debug_bundle is not None
    assert packetizer_result.packet_debug_bundle.packet_diagnostics
    assert packetizer_result.packet_debug_bundle.counts_by_family
