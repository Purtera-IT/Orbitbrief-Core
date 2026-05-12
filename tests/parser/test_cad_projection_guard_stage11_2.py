from __future__ import annotations

from orbitbrief_core.runtime_spine.extractors.narrative_claim_ontology import EvidenceRef, EvidenceRefSet, InternalClaim
from orbitbrief_core.runtime_spine.extractors.narrative_projector import project_internal_claims_to_field_claims


def _evidence() -> EvidenceRefSet:
    return EvidenceRefSet(
        packet_id="packet:cad:0001",
        primary_span_id="span:1",
        supporting_span_ids=("span:2",),
        all_span_ids=("span:1", "span:2"),
        refs=(EvidenceRef(span_id="span:1", role="anchor"), EvidenceRef(span_id="span:2", role="support")),
    )


def test_cad_high_confidence_projects_allowed_field() -> None:
    claim = InternalClaim(
        claim_id="claim:1",
        claim_family="site_location_claim",
        packet_id="packet:cad:0001",
        packet_family="site_identity_packet",
        claim_body="Dallas Clinic",
        confidence=0.9,
        status="asserted",
        verification_needed=False,
        stronger_source_needed=False,
        evidence=_evidence(),
        metadata={},
    )
    projected = project_internal_claims_to_field_claims((claim,))
    assert projected
    assert projected[0].field_path == "site_locations"


def test_cad_low_confidence_is_blocked_by_guard() -> None:
    claim = InternalClaim(
        claim_id="claim:2",
        claim_family="site_location_claim",
        packet_id="packet:cad:0002",
        packet_family="site_identity_packet",
        claim_body="Dallas Clinic",
        confidence=0.5,
        status="possible",
        verification_needed=False,
        stronger_source_needed=False,
        evidence=_evidence(),
        metadata={},
    )
    projected = project_internal_claims_to_field_claims((claim,))
    assert projected == ()


class _ProjectionPolicy:
    def projection_targets_for_claim_family(self, claim_family: str) -> tuple[str, ...]:
        if claim_family == "site_location_claim":
            return ("customer_name",)
        return ()


def test_cad_disallowed_target_path_is_blocked_even_with_policy() -> None:
    claim = InternalClaim(
        claim_id="claim:3",
        claim_family="site_location_claim",
        packet_id="packet:cad:0003",
        packet_family="site_identity_packet",
        claim_body="Dallas Clinic",
        confidence=0.93,
        status="asserted",
        verification_needed=False,
        stronger_source_needed=False,
        evidence=_evidence(),
        metadata={},
    )
    projected = project_internal_claims_to_field_claims((claim,), projection_policy=_ProjectionPolicy())
    assert projected == ()

