from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import domain_config_root
from .mapping_models import (
    AliasObservation,
    AliasResolverResult,
    ApprovedAliasEntry,
    CandidateTarget,
    HeaderBundle,
    MappingDecision,
    MappingDecisionBasis,
)
from .shared import make_id, utc_now


MAPPING_ROOT = domain_config_root() / "mapping" / "site_roster_spreadsheet"


@lru_cache(maxsize=1)
def load_field_catalog() -> dict[str, Any]:
    return yaml.safe_load((MAPPING_ROOT / "field_catalog.generated.yaml").read_text())


@lru_cache(maxsize=1)
def load_approved_aliases() -> list[ApprovedAliasEntry]:
    payload = yaml.safe_load((MAPPING_ROOT / "approved_aliases.yaml").read_text())
    return [ApprovedAliasEntry(**entry) for entry in payload["aliases"]]


@lru_cache(maxsize=1)
def load_mapping_policy() -> dict[str, Any]:
    return yaml.safe_load((MAPPING_ROOT / "mapping_policy.yaml").read_text())


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _family_for_header(bundle: HeaderBundle) -> str | None:
    name = bundle.header_normalized
    if any(token in name for token in ["store", "branch", "site", "location", "site code", "branch code"]):
        return "site_identity"
    if any(token in name for token in ["address", "city", "state", "zip", "postal", "country", "region", "timezone", "lat", "lon"]):
        return "geography"
    if any(token in name for token in ["wave", "status", "go live", "finish", "start", "schedule", "pilot"]):
        return "schedule"
    if any(token in name for token in ["badge", "escort", "access", "dock", "parking", "safety"]):
        return "access"
    if any(token in name for token in ["ready", "readiness", "blocked", "materials ready"]):
        return "readiness"
    if any(token in name for token in ["qty", "quantity", "count", "drops", "devices", "aps", "switches"]):
        return "quantities"
    if any(token in name for token in ["device", "model", "manufacturer", "inventory"]):
        return "devices"
    if any(token in name for token in ["blocker", "dependency", "risk"]):
        return "blockers"
    if any(token in name for token in ["price", "cost", "commercial", "nte", "billing"]):
        return "commercial"
    if any(token in name for token in ["note", "comment", "remarks"]):
        return "notes"
    if any(token in name for token in ["total sites", "wave count", "program", "rollout"]):
        return "program_rollup"
    return None


def _candidate_targets(bundle: HeaderBundle) -> list[CandidateTarget]:
    catalog = load_field_catalog()
    family = _family_for_header(bundle)
    candidates: list[CandidateTarget] = []
    for family_entry in catalog["families"]:
        if family and family_entry["family_id"] != family:
            continue
        for field in family_entry["fields"]:
            score = 0.2
            path = field["path"]
            if any(token in path.lower() for token in bundle.header_normalized.split()):
                score += 0.35
            if "date" in bundle.value_profile.dominant_type and "date" in path:
                score += 0.25
            if bundle.value_profile.looks_like_count and any(t in path for t in ["count", "quantity", "qty"]):
                score += 0.25
            if "id" in bundle.value_profile.dominant_type and any(t in path for t in ["site_id", "location_id", "store_number", "branch_code"]):
                score += 0.2
            candidates.append(CandidateTarget(target_path=path, score=round(score, 2)))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:5]


def _hard_checks(bundle: HeaderBundle, alias: ApprovedAliasEntry | None, target_path: str | None) -> tuple[bool, bool]:
    if not target_path:
        return False, False
    type_check = True
    neighbor_check = True
    if target_path.endswith("target_go_live_date") and not bundle.value_profile.looks_like_date:
        type_check = False
    if target_path.endswith("site_count") and bundle.header_position.column_index > 10:
        neighbor_check = False
    if alias and alias.row_scope_required == "summary_only" and bundle.header_position.column_index > 10:
        neighbor_check = False
    return type_check, neighbor_check


def resolve_alias(bundle: HeaderBundle, pipeline_run_id: str, file_fingerprint: str) -> AliasResolverResult:
    aliases = load_approved_aliases()
    policy = load_mapping_policy()
    debug = []
    normalized = bundle.header_normalized

    for alias in aliases:
        if bundle.modality not in alias.modality_scope:
            continue
        if alias.raw_alias == bundle.header_raw or alias.normalized_alias == normalized:
            type_ok, neighbor_ok = _hard_checks(bundle, alias, alias.target_path)
            score = 0.99 if alias.raw_alias == bundle.header_raw else 0.96
            decision_type = "accepted" if type_ok and neighbor_ok else "review_required"
            decision = MappingDecision(
                mapping_decision_id=make_id("mapping"),
                pipeline_run_id=pipeline_run_id,
                domain_id=bundle.domain_id,
                role_id=bundle.role_id,
                sheet_name=bundle.sheet_name,
                header_raw=bundle.header_raw,
                normalized_header=normalized,
                decision_type=decision_type,
                mapping_kind=alias.mapping_kind,
                target_path=alias.target_path,
                decision_basis=MappingDecisionBasis(
                    exact_alias_hit=True,
                    embedding_candidates_used=False,
                    type_check_passed=type_ok,
                    neighbor_context_passed=neighbor_ok,
                ),
                score=score,
                review_required=decision_type != "accepted",
                created_at=utc_now(),
            )
            debug.append("exact/rule alias match")
            return AliasResolverResult(decision=decision, approved_alias=alias, debug_trace=debug)

    candidates = _candidate_targets(bundle)
    debug.append(f"family_retrieval={_family_for_header(bundle)}")
    debug.append(f"candidate_count={len(candidates)}")
    if not candidates:
        observation = AliasObservation(
            observation_id=make_id("alias_obs"),
            domain_id=bundle.domain_id,
            role_id=bundle.role_id,
            modality=bundle.modality,
            file_fingerprint=file_fingerprint,
            sheet_name=bundle.sheet_name,
            header_raw=bundle.header_raw,
            header_normalized=normalized,
            header_position=bundle.header_position,
            sample_values=bundle.sample_values,
            value_profile=bundle.value_profile,
            candidate_targets=[],
            decision="unmapped",
            created_at=utc_now(),
        )
        decision = MappingDecision(
            mapping_decision_id=make_id("mapping"),
            pipeline_run_id=pipeline_run_id,
            domain_id=bundle.domain_id,
            role_id=bundle.role_id,
            sheet_name=bundle.sheet_name,
            header_raw=bundle.header_raw,
            normalized_header=normalized,
            decision_type="unmapped",
            mapping_kind="unmapped",
            target_path=None,
            decision_basis=MappingDecisionBasis(
                exact_alias_hit=False,
                embedding_candidates_used=True,
                type_check_passed=False,
                neighbor_context_passed=False,
            ),
            score=0.0,
            review_required=True,
            created_at=utc_now(),
        )
        return AliasResolverResult(decision=decision, candidate_observation=observation, debug_trace=debug)

    best = candidates[0]
    gap = best.score - (candidates[1].score if len(candidates) > 1 else 0.0)
    type_ok, neighbor_ok = _hard_checks(bundle, None, best.target_path)
    accept_auto_threshold = policy["accept_auto_threshold"]
    review_threshold = policy["review_threshold"]
    top2_gap_min = policy["top2_gap_min"]

    if best.score >= accept_auto_threshold and gap >= top2_gap_min and type_ok and neighbor_ok:
        decision_type = "accepted"
    elif best.score >= review_threshold:
        decision_type = "review_required"
    else:
        decision_type = "unmapped"

    observation = None
    if decision_type != "accepted":
        observation = AliasObservation(
            observation_id=make_id("alias_obs"),
            domain_id=bundle.domain_id,
            role_id=bundle.role_id,
            modality=bundle.modality,
            file_fingerprint=file_fingerprint,
            sheet_name=bundle.sheet_name,
            header_raw=bundle.header_raw,
            header_normalized=normalized,
            header_position=bundle.header_position,
            sample_values=bundle.sample_values,
            value_profile=bundle.value_profile,
            candidate_targets=candidates,
            decision="review_required" if decision_type == "review_required" else "unmapped",
            created_at=utc_now(),
        )

    decision = MappingDecision(
        mapping_decision_id=make_id("mapping"),
        pipeline_run_id=pipeline_run_id,
        domain_id=bundle.domain_id,
        role_id=bundle.role_id,
        sheet_name=bundle.sheet_name,
        header_raw=bundle.header_raw,
        normalized_header=normalized,
        decision_type=decision_type,
        mapping_kind="direct" if decision_type == "accepted" else "review_required",
        target_path=best.target_path if decision_type != "unmapped" else None,
        decision_basis=MappingDecisionBasis(
            exact_alias_hit=False,
            embedding_candidates_used=True,
            type_check_passed=type_ok,
            neighbor_context_passed=neighbor_ok,
        ),
        score=best.score,
        review_required=decision_type != "accepted",
        created_at=utc_now(),
    )
    return AliasResolverResult(decision=decision, candidate_observation=observation, debug_trace=debug)
