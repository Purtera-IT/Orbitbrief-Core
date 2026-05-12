from __future__ import annotations

import re

from .base import ClaimCandidate, ProcessedClaim

_CAD_PACKET_FAMILIES = {
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

_UPPER_TOKENS = {"HQ", "MDF", "IDF", "AP", "SW", "UPS", "TR"}


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


def _normalize_site_label(text: str) -> str:
    cleaned = re.sub(r"^(?:site|location)\s*[:\-]\s*", "", text, flags=re.IGNORECASE).strip()
    pieces = re.split(r"\s+", cleaned)
    out: list[str] = []
    for piece in pieces:
        token = re.sub(r"[^A-Za-z0-9\-]", "", piece)
        upper = token.upper()
        if upper in _UPPER_TOKENS:
            out.append(upper)
        elif token:
            out.append(token.capitalize())
    return " ".join(out).strip()


def _normalize_equipment_or_quantity(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    patterns = (
        (r"\b(ap)\s*[-_# ]?\s*(\d+)\b", "AP-{}"),
        (r"\b(sw|switch)\s*[-_# ]?\s*(\d+)\b", "SW-{}"),
        (r"\b(rack)\s*[-_# ]?\s*(\d+)\b", "RACK-{}"),
        (r"\b(panel)\s*[-_# ]?\s*(\d+)\b", "PANEL-{}"),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return fmt.format(match.group(2).zfill(2) if fmt.startswith("AP") else match.group(2))
    return cleaned


def _normalize_cad_field_value(path: str, value: object) -> object:
    if not isinstance(value, str):
        return value
    cleaned = re.sub(r"\s+", " ", value).strip()
    if path in {"site_locations[]", "site_locations"}:
        return _normalize_site_label(cleaned) or cleaned
    if path in {"known_quantities[]", "known_quantities"}:
        return _normalize_equipment_or_quantity(cleaned)
    if path in {
        "drawing_packet_metadata",
        "site_profile_from_drawings",
        "access_and_logistics[]",
        "access_and_logistics",
        "scope_included[]",
        "scope_included",
        "assumptions[]",
        "assumptions",
        "risks[]",
        "risks",
        "dependencies[]",
        "dependencies",
    }:
        return cleaned
    return value


def normalize_claims(candidates: tuple[ClaimCandidate, ...]) -> tuple[ProcessedClaim, ...]:
    normalized: list[ProcessedClaim] = []
    for candidate in candidates:
        confidence = max(0.0, min(1.0, float(candidate.confidence)))
        normalized_value = _normalize_value(candidate.candidate_value)
        packet_family = str(candidate.metadata.get("packet_family", "")).strip()
        if packet_family in _CAD_PACKET_FAMILIES:
            normalized_value = _normalize_cad_field_value(candidate.target_field_path, normalized_value)
        normalized.append(
            ProcessedClaim(
                claim_id=candidate.claim_id,
                claim_family=candidate.claim_family,
                target_field=candidate.target_field,
                target_field_path=candidate.target_field_path,
                normalized_value=normalized_value,
                confidence=confidence,
                evidence_span_ids=tuple(sorted(set(candidate.evidence_span_ids))),
                source_claim_ids=(candidate.claim_id,),
                metadata=dict(candidate.metadata),
            )
        )
    return tuple(normalized)
