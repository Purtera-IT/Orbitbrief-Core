from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_extract_and_postprocess
from orbitbrief_core.runtime_spine.extractors.narrative_extractor import run_narrative_extractor
from orbitbrief_core.runtime_spine.extractors.packet_to_claims import PacketExtractionContext, extract_claims_from_packet


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


def _packet(payload_id: str, family: str, confidence: float = 0.72) -> dict:
    return {
        "packet_id": payload_id,
        "span_ids": ("span_a", "span_b"),
        "primary_span_id": "span_a",
        "confidence": confidence,
        "metadata": {
            "packet_family": family,
            "uncertainty_markers": [],
            "packet_diagnostic": {"included": [{"span_id": "span_a"}, {"span_id": "span_b"}]},
        },
    }


def test_packet_to_claims_family_dispatch_is_bounded_and_evidence_backed() -> None:
    packet = _packet("packet:risk:0001", "risk_packet", confidence=0.68)
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="txt"))
    assert not diagnostics
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_family == "risk_claim"
    assert claim.evidence.all_span_ids
    assert claim.evidence.primary_span_id
    assert claim.status in {"asserted", "possible", "ambiguous", "needs_review"}


def test_narrative_extractor_emits_internal_and_field_claims_with_refs() -> None:
    packets = [
        _packet("packet:scope:0001", "scope_packet", confidence=0.77),
        _packet("packet:question:0002", "open_question_packet", confidence=0.52),
    ]
    result = run_narrative_extractor(role_id="transcript_or_notes", modality="txt", packet_candidates=packets)
    assert result["internal_claims"]
    assert result["field_claims"]
    for claim in result["internal_claims"]:
        evidence = claim["evidence"]["all_span_ids"]
        assert evidence
        assert claim["status"]
        assert "confidence" in claim
    for field_claim in result["field_claims"]:
        assert field_claim["evidence"]["all_span_ids"]
        assert field_claim["field_path"]
        assert field_claim["source_claim_id"]
    assert result["emits_business_claims"] is True


def test_parse_extract_and_postprocess_keeps_packet_scoped_claims() -> None:
    compiled_pack = _compiled_pack_stub()
    text = (
        "09:00 Alice: Deliverable is migration runbook.\n"
        "09:05 Alice: Risk is permit delay.\n"
        "09:07 Bob: Open question on site count?"
    )
    router_input = RouterInput(
        doc_id="stage6_1_e2e_001",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )
    result = parse_extract_and_postprocess(router_input=router_input, compiled_pack=compiled_pack)
    extraction_result = result.extraction_result
    assert result.pipeline_state == "extract"
    assert extraction_result.get("internal_claims")
    assert extraction_result.get("field_claims")
    assert all(claim.get("evidence", {}).get("all_span_ids") for claim in extraction_result["internal_claims"])



def test_packet_to_claims_uses_semantic_span_text_and_family_override() -> None:
    packet = {
        "packet_id": "packet:cluster:0001",
        "span_ids": ("span_scope", "span_assumption"),
        "primary_span_id": "span_scope",
        "confidence": 0.81,
        "evidence_rows": [
            {
                "span_id": "span_scope",
                "text": "Scope includes AP installation at Dallas HQ and Austin branch.",
                "normalized_text": "scope includes ap installation at dallas hq and austin branch",
                "parser_cues": ["scope_included"],
                "packet_families": ["scope_packet"],
                "authority_score": 0.82,
            },
            {
                "span_id": "span_assumption",
                "text": "Assumption is customer will provide after-hours access.",
                "normalized_text": "assumption is customer will provide after-hours access",
                "parser_cues": ["assumption"],
                "packet_families": ["assumption_packet"],
                "authority_score": 0.79,
            },
        ],
        "metadata": {
            "packet_family": "assumption_packet",
            "uncertainty_markers": ["family_conflict"],
            "packet_diagnostic": {
                "anchor": {"family_hints": ["scope_packet"]},
                "family": {"competing_family_hints": ["assumption_packet"]},
            },
        },
    }
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="txt"))
    claim_families = {claim.claim_family for claim in claims}
    claim_bodies = {claim.claim_family: claim.claim_body for claim in claims}
    assert claim_families == {"scope_included_claim", "assumption_claim"}
    assert claim_bodies["scope_included_claim"] == "AP installation at Dallas HQ and Austin branch"
    assert claim_bodies["assumption_claim"] == "customer will provide after-hours access"
    assert any(item.code == "semantic_family_override" for item in diagnostics)
