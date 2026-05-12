from __future__ import annotations

from orbitbrief_core.runtime_spine.extractors.narrative_claim_ontology import EvidenceRef, EvidenceRefSet, InternalClaim
from orbitbrief_core.runtime_spine.extractors.narrative_projector import project_internal_claims_to_field_claims
from orbitbrief_core.runtime_spine.extractors.postprocess import postprocess_extractor_output
from orbitbrief_core.runtime_spine.extractors.registry import ExtractorSpec
from orbitbrief_core.runtime_spine.postprocess import PostprocessPolicy


def _evidence() -> EvidenceRefSet:
    return EvidenceRefSet(
        packet_id="packet:cad:008",
        primary_span_id="span:anchor",
        supporting_span_ids=("span:support",),
        all_span_ids=("span:anchor", "span:support"),
        refs=(
            EvidenceRef(span_id="span:anchor", role="anchor"),
            EvidenceRef(span_id="span:support", role="support"),
        ),
    )


def _spec() -> ExtractorSpec:
    return ExtractorSpec(
        extractor_id="cad_stage11_8_spec",
        role_id="transcript_or_notes",
        kind="narrative",
        entrypoint="orbitbrief_core.runtime_spine.extractors.runtime_impl:run_narrative_extractor",
        supports_modalities=("cad_sheet", "schematic", "floorplan"),
        supports_discourse_types=("project_memo",),
        packet_profile="professional_services_text_v1",
        emits_business_claims=True,
        enabled=True,
    )


def test_cad_claim_projection_is_family_specific_and_conservative() -> None:
    claims = (
        InternalClaim(
            claim_id="claim:cad:drawing",
            claim_family="drawing_metadata_claim",
            packet_id="packet:cad:drawing",
            packet_family="drawing_metadata_packet",
            claim_body="Sheet Number: A-401",
            confidence=0.9,
            status="asserted",
            verification_needed=False,
            stronger_source_needed=False,
            evidence=_evidence(),
            metadata={},
        ),
        InternalClaim(
            claim_id="claim:cad:room",
            claim_family="network_room_claim",
            packet_id="packet:cad:room",
            packet_family="network_room_or_closet_packet",
            claim_body="MDF-01 telecom closet",
            confidence=0.86,
            status="asserted",
            verification_needed=False,
            stronger_source_needed=False,
            evidence=_evidence(),
            metadata={},
        ),
        InternalClaim(
            claim_id="claim:cad:constructability",
            claim_family="constructability_claim",
            packet_id="packet:cad:constructability",
            packet_family="constructability_packet",
            claim_body="After-hours access requires escort and depends on permit approval.",
            confidence=0.84,
            status="asserted",
            verification_needed=False,
            stronger_source_needed=False,
            evidence=_evidence(),
            metadata={},
        ),
    )
    projected = project_internal_claims_to_field_claims(claims)
    paths = {claim.field_path for claim in projected}
    assert "drawing_packet_metadata" in paths
    assert "site_profile_from_drawings" in paths
    assert "access_and_logistics" in paths
    assert "dependencies" in paths


def test_cad_projection_blocks_noise_and_overreach() -> None:
    claims = (
        InternalClaim(
            claim_id="claim:cad:noise_scope",
            claim_family="scope_note_claim",
            packet_id="packet:cad:noise_scope",
            packet_family="note_scope_packet",
            claim_body="Legend: Symbol table for reference only",
            confidence=0.9,
            status="asserted",
            verification_needed=False,
            stronger_source_needed=False,
            evidence=_evidence(),
            metadata={},
        ),
        InternalClaim(
            claim_id="claim:cad:topology_weak",
            claim_family="topology_hint_claim",
            packet_id="packet:cad:topology_weak",
            packet_family="topology_hint_packet",
            claim_body="Possible adjacency unclear",
            confidence=0.78,
            status="asserted",
            verification_needed=False,
            stronger_source_needed=False,
            evidence=_evidence(),
            metadata={},
        ),
    )
    projected = project_internal_claims_to_field_claims(claims)
    assert projected == ()


def test_cad_postprocess_normalizes_site_labels_and_blocks_revision_leakage() -> None:
    output = {
        "field_claims": [
            {
                "claim_family": "site_location_claim",
                "field_path": "site_locations",
                "value": "site: los angeles hq",
                "source_claim_id": "claim:1",
                "confidence": 0.86,
                "status": "asserted",
                "evidence": {"packet_id": "packet:1", "primary_span_id": "span:1", "supporting_span_ids": [], "all_span_ids": ["span:1"], "refs": [{"span_id": "span:1", "role": "anchor"}]},
                "metadata": {"packet_family": "site_identity_packet"},
            },
            {
                "claim_family": "scope_note_claim",
                "field_path": "scope_included",
                "value": "Rev A: Updated rack clearance labels",
                "source_claim_id": "claim:2",
                "confidence": 0.82,
                "status": "asserted",
                "evidence": {"packet_id": "packet:2", "primary_span_id": "span:2", "supporting_span_ids": [], "all_span_ids": ["span:2"], "refs": [{"span_id": "span:2", "role": "anchor"}]},
                "metadata": {"packet_family": "revision_change_packet"},
            },
        ]
    }
    result = postprocess_extractor_output(
        extractor_spec=_spec(),
        extraction_output=output,
        policy=PostprocessPolicy(
            emits_business_claims=True,
            allowed_claim_families=frozenset({"site_location_claim", "scope_note_claim"}),
            allowed_field_paths=frozenset({"site_locations", "scope_included"}),
            require_evidence_refs=True,
        ),
    )
    assert result["summary"]["claims_emitted_count"] == 1
    emitted = result["normalized_output"]["field_claims"][0]
    assert emitted["target_field_path"] == "site_locations"
    assert emitted["candidate_value"] == "Los Angeles HQ"
    reason_codes = {row["reason_code"] for row in result["rejected_claims"]}
    assert "cad_revision_leak_blocked" in reason_codes

