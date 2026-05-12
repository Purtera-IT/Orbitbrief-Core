from __future__ import annotations

from typing import Any, Mapping

from .registry import ExtractorSpec
from ..postprocess import ClaimCandidate, ExtractorOutput, PostprocessPolicy, run_postprocess


def _candidate_from_mapping(item: Mapping[str, Any], idx: int) -> ClaimCandidate | None:
    # New 6.2/6.3 field-claim IR shape.
    if "field_path" in item and "value" in item:
        source_claim_id = str(item.get("source_claim_id", "")).strip()
        if not source_claim_id:
            return None
        claim_family = str(item.get("claim_family", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        if not claim_family or not field_path:
            return None
        target_field = field_path.split(".")[0].split("[")[0] if field_path else ""
        evidence_payload = item.get("evidence", {})
        evidence_span_ids_raw: Any = ()
        if isinstance(evidence_payload, Mapping):
            evidence_span_ids_raw = evidence_payload.get("all_span_ids", ())
    else:
        required = ("claim_family", "target_field", "target_field_path", "candidate_value", "confidence")
        if any(key not in item for key in required):
            return None
        source_claim_id = str(item.get("claim_id", f"candidate:{idx:04d}"))
        claim_family = str(item.get("claim_family", "")).strip()
        target_field = str(item.get("target_field", "")).strip()
        field_path = str(item.get("target_field_path", "")).strip()
        evidence_span_ids_raw = item.get("evidence_span_ids", ())

    if isinstance(evidence_span_ids_raw, list):
        evidence_span_ids = tuple(str(value) for value in evidence_span_ids_raw)
    elif isinstance(evidence_span_ids_raw, tuple):
        evidence_span_ids = tuple(str(value) for value in evidence_span_ids_raw)
    else:
        evidence_span_ids = ()
    confidence = item.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        confidence = 0.0
    candidate_value = item.get("value") if "value" in item else item.get("candidate_value")
    metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), Mapping) else {}
    metadata.setdefault("source_claim_id", source_claim_id)

    return ClaimCandidate(
        claim_id=source_claim_id,
        claim_family=claim_family,
        target_field=target_field,
        target_field_path=field_path,
        candidate_value=candidate_value,
        confidence=float(confidence),
        evidence_span_ids=evidence_span_ids,
        metadata=metadata,
    )


def postprocess_extractor_output(
    *,
    extractor_spec: ExtractorSpec | None,
    extraction_output: Mapping[str, Any],
    policy: PostprocessPolicy,
) -> dict[str, Any]:
    """Deterministic postprocess pipeline for extractor claim candidates."""
    output = dict(extraction_output)
    raw_claims = output.get("field_claims")
    claims = raw_claims if isinstance(raw_claims, list) else []
    candidates: list[ClaimCandidate] = []
    dropped_invalid_count = 0
    for idx, item in enumerate(claims):
        if not isinstance(item, Mapping):
            dropped_invalid_count += 1
            continue
        candidate = _candidate_from_mapping(item, idx)
        if candidate is None:
            dropped_invalid_count += 1
            continue
        candidates.append(candidate)

    extractor_id = extractor_spec.extractor_id if extractor_spec is not None else "none"
    extractor_kind = extractor_spec.kind if extractor_spec is not None else "none"

    result = run_postprocess(
        extractor_output=ExtractorOutput(candidates=tuple(candidates), metadata={"extractor_id": extractor_id}),
        policy=policy,
    )

    normalized_claims = [
        {
            "claim_id": claim.claim_id,
            "claim_family": claim.claim_family,
            "target_field": claim.target_field,
            "target_field_path": claim.target_field_path,
            "candidate_value": claim.normalized_value,
            "confidence": claim.confidence,
            "evidence_span_ids": list(claim.evidence_span_ids),
            "source_claim_ids": list(claim.source_claim_ids),
            "metadata": dict(claim.metadata),
        }
        for claim in result.surviving_claims
    ]
    rejected_claims = [
        {
            "claim_id": rejection.claim_id,
            "reason_code": rejection.reason_code,
            "message": rejection.message,
            "metadata": dict(rejection.metadata),
        }
        for rejection in result.rejected_claims
    ]
    contradictions = [
        {
            "contradiction_id": group.contradiction_id,
            "target_field_path": group.target_field_path,
            "claim_ids": list(group.claim_ids),
            "reason_code": group.reason_code,
            "metadata": dict(group.metadata),
        }
        for group in result.contradiction_groups
    ]
    review_flags = [
        {
            "flag_id": flag.flag_id,
            "code": flag.code,
            "severity": flag.severity,
            "message": flag.message,
            "claim_ids": list(flag.claim_ids),
            "metadata": dict(flag.metadata),
        }
        for flag in result.review_flags
    ]
    output["field_claims"] = normalized_claims

    result = {
        "extractor_id": extractor_id,
        "extractor_kind": extractor_kind,
        "business_claims_allowed": policy.emits_business_claims,
        "claims_input_count": len(candidates),
        "claims_emitted_count": len(normalized_claims),
        "blocked_claims_count": sum(1 for rejection in rejected_claims if rejection["reason_code"] == "business_claims_not_allowed"),
        "dropped_invalid_claims_count": dropped_invalid_count,
        "deduped_claims_count": sum(1 for rejection in rejected_claims if rejection["reason_code"] == "duplicate_merged"),
        "rejected_claims_count": len(rejected_claims),
        "contradiction_group_count": len(contradictions),
        "review_flag_count": len(review_flags),
        "status": "ok" if len(normalized_claims) or not rejected_claims else "rejected",
    }
    if result["blocked_claims_count"] > 0:
        result["status"] = "claims_blocked_by_policy"

    return {
        "normalized_output": output,
        "rejected_claims": rejected_claims,
        "contradiction_groups": contradictions,
        "review_flags": review_flags,
        "summary": result,
    }
