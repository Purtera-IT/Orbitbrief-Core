from __future__ import annotations

from orbitbrief_core.runtime_spine.extractors.narrative_extractor import run_narrative_extractor
from orbitbrief_core.runtime_spine.extractors.packet_to_claims import PacketExtractionContext, extract_claims_from_packet


def _packet(*, packet_id: str, family: str, text: str, confidence: float = 0.82, packet_state: str = "extract", uncertainty_markers: list[str] | None = None) -> dict:
    markers = uncertainty_markers or []
    return {
        "packet_id": packet_id,
        "span_ids": ("span:anchor", "span:support"),
        "primary_span_id": "span:anchor",
        "confidence": confidence,
        "evidence_rows": [
            {
                "span_id": "span:anchor",
                "text": text,
                "normalized_text": text.lower(),
                "authority_score": confidence,
                "metadata": {"kind": "note_block"},
            },
            {
                "span_id": "span:support",
                "text": "Attached support region reference",
                "normalized_text": "attached support region reference",
                "authority_score": max(0.4, confidence - 0.1),
                "metadata": {"kind": "equipment_label"},
            },
        ],
        "metadata": {
            "packet_family": family,
            "packet_state": packet_state,
            "uncertainty_markers": markers,
            "packet_diagnostic": {
                "anchor": {"anchor_span_id": "span:anchor", "family_hints": [family]},
                "included": [{"span_id": "span:anchor"}, {"span_id": "span:support"}],
                "excluded": [],
                "family": {"assigned_family": family, "rationale_codes": ["cad_anchor_kind_match"]},
                "graph_edges_used": ["edge:evidence:000001:span:anchor:span:support:references"],
            },
            "cad_packetizer": {
                "anchor_kind": "note_block",
                "family_score": confidence,
                "review_reasons": [],
            },
        },
    }


def test_cad_packet_to_claims_emits_expected_internal_family_with_evidence() -> None:
    packet = _packet(
        packet_id="packet:cad:001",
        family="drawing_metadata_packet",
        text="Sheet Number: A-401",
        confidence=0.86,
    )
    claims, diagnostics = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_family == "drawing_metadata_claim"
    assert claim.claim_body
    assert claim.evidence.primary_span_id == "span:anchor"
    assert claim.evidence.all_span_ids
    assert claim.metadata.get("packet_diagnostics")
    assert any(item.code == "cad_claim_extracted" for item in diagnostics)


def test_cad_extractor_family_specific_mapping_is_bounded() -> None:
    packet = _packet(
        packet_id="packet:cad:002",
        family="network_room_or_closet_packet",
        text="MDF-01 telecom closet",
        confidence=0.81,
    )
    claims, _ = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="floorplan"))
    assert len(claims) == 1
    assert claims[0].claim_family == "network_room_claim"
    # Ensure it does not overreach into unrelated family types.
    assert claims[0].claim_family != "drawing_metadata_claim"


def test_cad_ambiguous_packet_marks_review_state_conservatively() -> None:
    packet = _packet(
        packet_id="packet:cad:003",
        family="topology_hint_packet",
        text="Possible uplink adjacency from closet to switch",
        confidence=0.38,
        packet_state="parked",
        uncertainty_markers=["family_conflict", "parked"],
    )
    claims, _ = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="schematic"))
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_family == "topology_hint_claim"
    assert claim.status == "needs_review"
    assert claim.verification_needed is True
    assert "parked" in claim.metadata.get("review_flags", [])


def test_run_narrative_extractor_handles_cad_packet_batch_without_global_reopen() -> None:
    packets = [
        _packet(packet_id="packet:cad:010", family="site_identity_packet", text="Site: Dallas Clinic", confidence=0.84),
        _packet(packet_id="packet:cad:011", family="constructability_packet", text="Escort required for after-hours closet access", confidence=0.74, packet_state="review_required", uncertainty_markers=["review_required"]),
    ]
    result = run_narrative_extractor(
        role_id="transcript_or_notes",
        modality="cad_sheet",
        packet_candidates=packets,
    )
    families = {item["claim_family"] for item in result["internal_claims"]}
    assert "site_location_claim" in families
    assert "constructability_claim" in families
    assert all(item["evidence"]["all_span_ids"] for item in result["internal_claims"])

