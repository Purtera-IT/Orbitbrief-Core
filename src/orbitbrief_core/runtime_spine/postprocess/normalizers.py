from __future__ import annotations

from .base import ClaimCandidate, ProcessedClaim


def _normalize_value(value):
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        lowered = cleaned.lower()
        if lowered in {"true", "yes", "y"}:
            return True
        if lowered in {"false", "no", "n"}:
            return False
        try:
            if "." in cleaned:
                return float(cleaned)
            return int(cleaned)
        except ValueError:
            return cleaned
    return value


def normalize_claims(candidates: tuple[ClaimCandidate, ...]) -> tuple[ProcessedClaim, ...]:
    normalized: list[ProcessedClaim] = []
    for candidate in candidates:
        confidence = max(0.0, min(1.0, float(candidate.confidence)))
        normalized.append(
            ProcessedClaim(
                claim_id=candidate.claim_id,
                claim_family=candidate.claim_family,
                target_field=candidate.target_field,
                target_field_path=candidate.target_field_path,
                normalized_value=_normalize_value(candidate.candidate_value),
                confidence=confidence,
                evidence_span_ids=tuple(sorted(set(candidate.evidence_span_ids))),
                source_claim_ids=(candidate.claim_id,),
                metadata=dict(candidate.metadata),
            )
        )
    return tuple(normalized)
