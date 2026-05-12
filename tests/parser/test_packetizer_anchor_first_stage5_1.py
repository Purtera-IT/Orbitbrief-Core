from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.packet_policies import PACKET_POLICIES, DEFAULT_PACKET_POLICY
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


def test_anchor_first_prefers_current_authored_anchor_over_quoted_context() -> None:
    text = (
        "09:00 Alice: Deliverable is migration runbook by Friday.\n"
        "> 08:30 Bob: deliverable maybe next quarter.\n"
        "09:05 Alice: Responsibility stays with operations lead."
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packet_anchor_5_1_001", filename="thread.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    packet = result.packet_candidates[0]
    diagnostic = packet.metadata["packet_diagnostic"]
    anchor_span_id = diagnostic["anchor"]["anchor_span_id"]
    assert anchor_span_id == packet.primary_span_id
    anchor_reason_codes = set(diagnostic["anchor"]["reason_codes"])
    assert anchor_reason_codes
    assert "quoted_context_disallowed" not in anchor_reason_codes


def test_graph_neighborhood_expansion_is_bounded_by_family_policy() -> None:
    text = (
        "09:00 Alice: Risk is permit delay.\n"
        "09:01 Alice: Mitigation is permit pre-check this week.\n"
        "09:02 Alice: Dependency is zoning office response.\n"
        "09:03 Alice: Scope includes parser runtime delivery.\n"
        "09:04 Alice: Open question on site count?"
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packet_anchor_5_1_002", filename="context.txt", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    for packet in result.packet_candidates:
        diagnostic = packet.metadata["packet_diagnostic"]
        family = diagnostic["family"]["assigned_family"]
        policy = PACKET_POLICIES.get(family, DEFAULT_PACKET_POLICY)
        assert len(diagnostic["included"]) <= policy.max_support_spans
        # Graph-backed expansion should preserve evidence linkage.
        assert isinstance(diagnostic["graph_edges_used"], list)


def test_family_assignment_happens_after_assembly_with_structured_rationale() -> None:
    text = (
        "# Risks\n"
        "Permit review remains unresolved.\n\n"
        "## Notes\n"
        "Timeline remains uncertain pending office response."
    )
    result = parse_and_packetize(
        router_input=RouterInput(doc_id="packet_anchor_5_1_003", filename="risk.md", raw_text_preview=text, metadata={"raw_text": text}),
        compiled_pack=_compiled_pack_stub(),
    )
    assert result.packet_candidates
    packet = result.packet_candidates[0]
    diagnostic = packet.metadata["packet_diagnostic"]
    family = diagnostic["family"]["assigned_family"]
    assert family
    assert diagnostic["family"]["rationale_codes"]
    assert isinstance(diagnostic["family"]["competing_family_hints"], list)
    components = {item["component"] for item in diagnostic["score_contributions"]}
    assert "family_consistency" in components
