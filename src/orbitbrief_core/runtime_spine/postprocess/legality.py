from __future__ import annotations

import re

from .base import ClaimCandidate, PostprocessPolicy, RejectedClaim


_FALLBACK_MARKER_RE = re.compile(r"\b(?:anchor=|supports=|packet:|claim:|span:)\b", flags=re.IGNORECASE)
_QUANTITY_VALUE_RE = re.compile(
    r"^(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s*(?:months?|weeks?|days?|sites?|locations?|offices?|branches?|users?|seats?|devices?|units?|assets?|resources?|fte|drops?|aps?|switch(?:es)?|engineers?|technicians?)$",
    flags=re.IGNORECASE,
)
_PRICING_VALUE_RE = re.compile(r"\b(?:fixed fee|monthly billing|monthly in arrears|billed monthly|time and materials|t&m)\b", flags=re.IGNORECASE)
_CAD_NOISE_RE = re.compile(r"\b(?:legend|symbol table|boilerplate|stamp|not for construction|title block border)\b", flags=re.IGNORECASE)
_CAD_EQUIPMENT_RE = re.compile(r"\b(?:ap[-\s_#]?\d+|sw(?:itch)?[-\s_#]?\d+|rack[-\s_#]?\d+|panel[-\s_#]?\d+)\b", flags=re.IGNORECASE)
_CAD_REVISION_RE = re.compile(r"\brev(?:ision)?\s*[a-z0-9]+\b", flags=re.IGNORECASE)


def _value_text(value: object) -> str:
    return " ".join(str(value).split()).strip()


def _plausible_for_field(candidate: ClaimCandidate) -> bool:
    text = _value_text(candidate.candidate_value)
    if not text:
        return False
    path = candidate.target_field_path
    if path in {"scope_included[].quantity", "scope_included[].unit"}:
        return bool(_QUANTITY_VALUE_RE.match(text))
    if path == "site_count":
        return bool(re.fullmatch(r"\d{1,4}", text))
    if path == "site_locations[]":
        return len(text) <= 80 and not _FALLBACK_MARKER_RE.search(text) and any(ch.isalpha() for ch in text)
    if path == "commercial_structure.pricing_model":
        return bool(_PRICING_VALUE_RE.search(text))
    if path in {"known_quantities[]", "known_quantities"}:
        return bool(_QUANTITY_VALUE_RE.match(text) or _CAD_EQUIPMENT_RE.search(text))
    if path == "drawing_packet_metadata":
        return len(text) <= 220 and not _FALLBACK_MARKER_RE.search(text)
    if path == "site_profile_from_drawings":
        return len(text) <= 180 and not _FALLBACK_MARKER_RE.search(text)
    if path == "primary_customer_contact":
        parts = [part for part in re.findall(r"[A-Za-z][A-Za-z'.-]+", text) if part]
        titled = sum(1 for part in parts if part[:1].isupper())
        return titled >= 2 and not _FALLBACK_MARKER_RE.search(text)
    return True


def enforce_legality(
    *,
    candidates: tuple[ClaimCandidate, ...],
    policy: PostprocessPolicy,
) -> tuple[tuple[ClaimCandidate, ...], list[RejectedClaim]]:
    surviving: list[ClaimCandidate] = []
    rejected: list[RejectedClaim] = []
    for candidate in candidates:
        packet_family = str(candidate.metadata.get("packet_family", "")).strip()
        is_cad_family = packet_family in {
            "drawing_metadata_packet",
            "site_identity_packet",
            "network_room_or_closet_packet",
            "equipment_reference_packet",
            "note_scope_packet",
            "revision_change_packet",
            "topology_hint_packet",
            "constructability_packet",
            "known_quantity_packet",
        }
        if not policy.emits_business_claims:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="business_claims_not_allowed",
                    message="Extractor lane is not allowed to emit business claims.",
                )
            )
            continue
        if policy.allowed_claim_families and candidate.claim_family not in policy.allowed_claim_families:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="unsupported_claim_family",
                    message=f"Claim family {candidate.claim_family!r} is not allowed.",
                )
            )
            continue
        if policy.allowed_field_paths and candidate.target_field_path not in policy.allowed_field_paths:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="illegal_field_path",
                    message=f"Field path {candidate.target_field_path!r} is not allowed.",
                )
            )
            continue
        # Enforce basic field/path consistency to prevent cross-slot drift.
        if not (
            candidate.target_field_path == candidate.target_field
            or candidate.target_field_path.startswith(candidate.target_field + ".")
            or candidate.target_field_path.startswith(candidate.target_field + "[")
        ):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="field_path_mismatch",
                    message=(
                        f"target_field {candidate.target_field!r} does not align with "
                        f"target_field_path {candidate.target_field_path!r}."
                    ),
                )
            )
            continue
        if policy.require_evidence_refs and not candidate.evidence_span_ids:
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="missing_evidence_refs",
                    message="Claim is missing evidence references.",
                )
            )
            continue
        if policy.require_evidence_refs and any((not span_id.strip()) for span_id in candidate.evidence_span_ids):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="malformed_evidence_refs",
                    message="Claim contains malformed evidence references.",
                )
            )
            continue
        if candidate.candidate_value in (None, ""):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="unsupported_value",
                    message="Claim candidate value is empty.",
                )
            )
            continue
        if is_cad_family and candidate.target_field_path in {
            "scope_included[]",
            "scope_included",
            "assumptions[]",
            "assumptions",
            "risks[]",
            "risks",
            "dependencies[]",
            "dependencies",
            "access_and_logistics[]",
            "access_and_logistics",
        }:
            text = _value_text(candidate.candidate_value)
            if _CAD_NOISE_RE.search(text):
                rejected.append(
                    RejectedClaim(
                        claim_id=candidate.claim_id,
                        reason_code="cad_noise_projection_blocked",
                        message="CAD metadata/noise content is not allowed to project into semantic business fields.",
                    )
                )
                continue
            if candidate.target_field_path in {"scope_included[]", "scope_included", "assumptions[]", "assumptions"} and _CAD_REVISION_RE.search(text):
                rejected.append(
                    RejectedClaim(
                        claim_id=candidate.claim_id,
                        reason_code="cad_revision_leak_blocked",
                        message="CAD revision metadata is not allowed to project into scope/assumptions fields.",
                    )
                )
                continue
        if not _plausible_for_field(candidate):
            rejected.append(
                RejectedClaim(
                    claim_id=candidate.claim_id,
                    reason_code="field_value_not_plausible",
                    message=f"Claim value is not plausible for field path {candidate.target_field_path!r}.",
                )
            )
            continue
        surviving.append(candidate)
    return tuple(surviving), rejected
