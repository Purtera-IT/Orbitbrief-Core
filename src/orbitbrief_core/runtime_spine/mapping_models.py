from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .contracts import SpineModel


class HeaderPosition(SpineModel):
    sheet_index: int
    column_index: int


class ValueProfile(SpineModel):
    dominant_type: str
    distinct_ratio: float
    null_ratio: float
    looks_like_date: bool = False
    looks_like_count: bool = False


class HeaderBundle(SpineModel):
    role_id: str
    domain_id: str
    modality: str
    header_raw: str
    header_normalized: str
    sheet_name: str
    neighbor_headers: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    value_profile: ValueProfile
    header_position: HeaderPosition


class ApprovedAliasEntry(SpineModel):
    alias_id: str
    raw_alias: str
    normalized_alias: str
    target_path: str
    family_id: str
    mapping_kind: Literal["direct", "multi_field_split", "composite_identity", "note_sink", "summary_only", "ignore"]
    modality_scope: list[str] = Field(default_factory=list)
    sheet_scope: list[str] = Field(default_factory=list)
    sample_value_shapes: list[str] = Field(default_factory=list)
    confidence_policy: str | None = None
    row_scope_required: str | None = None
    split_targets: list[str] = Field(default_factory=list)
    note_sink_targets: list[str] = Field(default_factory=list)
    status: Literal["approved"] = "approved"
    created_from: str | None = None
    notes: str | None = None
    source_ref: dict = Field(default_factory=dict)
    version: str = "1.0.0"


class CandidateTarget(SpineModel):
    target_path: str
    score: float


class AliasObservation(SpineModel):
    observation_id: str
    domain_id: str
    role_id: str
    modality: str
    file_fingerprint: str
    sheet_name: str
    header_raw: str
    header_normalized: str
    header_position: HeaderPosition
    sample_values: list[str] = Field(default_factory=list)
    value_profile: ValueProfile
    candidate_targets: list[CandidateTarget] = Field(default_factory=list)
    decision: Literal["review_required", "unmapped"]
    created_at: datetime


class MappingDecisionBasis(SpineModel):
    exact_alias_hit: bool = False
    embedding_candidates_used: bool = False
    type_check_passed: bool = False
    neighbor_context_passed: bool = False


class MappingDecision(SpineModel):
    mapping_decision_id: str
    pipeline_run_id: str
    domain_id: str
    role_id: str
    sheet_name: str
    header_raw: str
    normalized_header: str
    decision_type: Literal["accepted", "review_required", "unmapped"]
    mapping_kind: str
    target_path: str | None = None
    decision_basis: MappingDecisionBasis
    score: float
    review_required: bool
    created_at: datetime


class AliasResolverResult(SpineModel):
    decision: MappingDecision
    approved_alias: ApprovedAliasEntry | None = None
    candidate_observation: AliasObservation | None = None
    debug_trace: list[str] = Field(default_factory=list)
