from __future__ import annotations

import re
from typing import Any

from .mapping_models import ApprovedAlias, CandidateObservation, HeaderBundle, MappingDecision, MappingResolution


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


_APPROVED = {
    "go live": ApprovedAlias(header_alias="Go Live", target_path="site_roster_rows[].target_go_live_date", mapping_kind="exact"),
    "city state zip": ApprovedAlias(header_alias="City / State / Zip", target_path="site_roster_rows[]", mapping_kind="multi_field_split"),
    "total sites": ApprovedAlias(header_alias="Total Sites", target_path="site_count", mapping_kind="exact"),
    "site name": ApprovedAlias(header_alias="Site Name", target_path="site_roster_rows[].site_name", mapping_kind="exact"),
    "site id": ApprovedAlias(header_alias="Site ID", target_path="site_roster_rows[].site_id", mapping_kind="exact"),
    "address": ApprovedAlias(header_alias="Address", target_path="site_roster_rows[].address", mapping_kind="exact"),
    "notes": ApprovedAlias(header_alias="Notes", target_path="site_roster_rows[].notes", mapping_kind="exact"),
    "ap count": ApprovedAlias(header_alias="AP Count", target_path="site_roster_rows[].ap_count", mapping_kind="exact"),
}


def load_approved_aliases() -> dict[str, dict[str, Any]]:
    return {key: alias.model_dump(mode="json", exclude_none=True) for key, alias in _APPROVED.items()}


def load_field_catalog() -> dict[str, Any]:
    return {
        "families": [
            {"family": "site_roster", "fields": ["site_count", "site_roster_rows", "location_details"]},
            {"family": "narrative", "fields": ["project_summary", "open_questions", "known_assumptions"]},
        ]
    }


def load_mapping_policy() -> dict[str, Any]:
    return {
        "accept_auto_threshold": 0.92,
        "review_threshold": 0.55,
    }


def resolve_alias(bundle: HeaderBundle, *, pipeline_run_id: str, file_fingerprint: str) -> MappingResolution:
    normalized = _normalize(bundle.header_normalized or bundle.header_raw)
    alias = _APPROVED.get(normalized)
    if alias is not None:
        confidence = 0.99 if alias.mapping_kind == "exact" else 0.96
        return MappingResolution(
            decision=MappingDecision(decision_type="accepted", target_path=alias.target_path, confidence=confidence),
            approved_alias=alias,
        )

    if bundle.value_profile.looks_like_count and "count" in normalized:
        return MappingResolution(
            decision=MappingDecision(decision_type="accepted", target_path="site_count", confidence=0.93),
            approved_alias=ApprovedAlias(header_alias=bundle.header_raw, target_path="site_count", mapping_kind="heuristic"),
        )

    return MappingResolution(
        decision=MappingDecision(decision_type="review_required", target_path=None, confidence=0.3),
        candidate_observation=CandidateObservation(
            header_raw=bundle.header_raw,
            header_normalized=normalized,
            pipeline_run_id=pipeline_run_id,
            file_fingerprint=file_fingerprint,
        ),
    )


__all__ = [
    "load_approved_aliases",
    "load_field_catalog",
    "load_mapping_policy",
    "resolve_alias",
]
