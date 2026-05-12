from __future__ import annotations

from typing import Any, Mapping

from .example_support import ExampleSupportAssets
from .narrative_claim_ontology import ExtractionDiagnostic, InternalClaim, NarrativeExtractionResult
from .narrative_projector import project_internal_claims_to_field_claims
from .packet_to_claims import PacketExtractionContext, extract_claims_from_packet


def run_narrative_extractor(
    *,
    role_id: str,
    modality: str,
    packet_candidates: list[dict[str, Any]],
    compiled_runtime_policy: Any | None = None,
) -> dict[str, Any]:
    """Bounded packet-to-claims narrative extraction orchestration."""
    context = PacketExtractionContext(role_id=role_id, modality=modality)
    internal_claims: list[InternalClaim] = []
    diagnostics: list[ExtractionDiagnostic] = []
    review_flags: list[str] = []
    policy_allowed_claim_families: frozenset[str] = frozenset()
    support_assets: ExampleSupportAssets | None = None
    if compiled_runtime_policy is not None:
        allowed_getter = getattr(compiled_runtime_policy, "allowed_claim_families_for_role", None)
        if callable(allowed_getter):
            policy_allowed_claim_families = frozenset(allowed_getter(role_id))
        support_assets = ExampleSupportAssets.from_rows(
            retrieval_exemplars=tuple(getattr(compiled_runtime_policy, "retrieval_exemplars", ())),
            negative_examples=tuple(getattr(compiled_runtime_policy, "negative_examples", ())),
        )

    for packet in packet_candidates:
        if not isinstance(packet, Mapping):
            diagnostics.append(
                ExtractionDiagnostic(
                    code="packet_payload_invalid",
                    message="Packet payload row is not a mapping.",
                )
            )
            continue
        claims, packet_diagnostics = extract_claims_from_packet(packet, context)
        for claim in claims:
            if policy_allowed_claim_families and claim.claim_family not in policy_allowed_claim_families:
                diagnostics.append(
                    ExtractionDiagnostic(
                        code="claim_family_not_allowed_by_compiled_policy",
                        message="Claim family rejected by compiled runtime policy.",
                        packet_id=claim.packet_id,
                        metadata={
                            "claim_family": claim.claim_family,
                            "role_id": role_id,
                            "evidence_span_ids": list(claim.evidence.all_span_ids),
                        },
                    )
                )
                continue
            internal_claims.append(claim)
            if support_assets is not None:
                overlap_ids = support_assets.negative_overlap(claim.claim_body, claim_family=claim.claim_family, modality=modality)
                if overlap_ids:
                    review_flags.append("negative_example_overlap")
                    diagnostics.append(
                        ExtractionDiagnostic(
                            code="negative_example_overlap",
                            message="Claim text overlaps compiled negative examples and should be reviewed.",
                            packet_id=claim.packet_id,
                            metadata={
                                "negative_example_ids": list(overlap_ids),
                                "claim_family": claim.claim_family,
                                "evidence_span_ids": list(claim.evidence.all_span_ids),
                            },
                        )
                    )
        diagnostics.extend(packet_diagnostics)
        for claim in claims:
            if claim.status in {"ambiguous", "needs_review"}:
                review_flags.append("claim_needs_review")
            if claim.verification_needed:
                review_flags.append("verification_needed")
            if claim.stronger_source_needed:
                review_flags.append("stronger_source_needed")

    field_claims = project_internal_claims_to_field_claims(internal_claims, projection_policy=compiled_runtime_policy)
    extraction_result = NarrativeExtractionResult(
        internal_claims=tuple(internal_claims),
        field_claims=field_claims,
        extraction_diagnostics=tuple(diagnostics),
        review_flags=tuple(dict.fromkeys(review_flags)),
    )
    payload = extraction_result.to_dict()
    payload.update(
        {
            "role_id": role_id,
            "modality": modality,
            "packet_count": len(packet_candidates),
            "emits_business_claims": True,
            "compiled_policy_used": compiled_runtime_policy is not None,
        }
    )
    if support_assets is not None:
        payload["support_assets_summary"] = {
            "retrieval_exemplar_count": len(support_assets.exemplars),
            "negative_example_count": len(support_assets.negatives),
        }
    return payload
