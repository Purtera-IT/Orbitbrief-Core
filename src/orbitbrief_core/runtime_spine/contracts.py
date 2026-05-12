from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class BoundingBox(_Model):
    x0: float | int
    y0: float | int
    x1: float | int
    y1: float | int


class SourceRef(_Model):
    artifact_id: str
    artifact_name: str
    artifact_path: str
    artifact_hash: str


class ConfigSnapshotRef(_Model):
    id: str
    snapshot_id: str
    snapshot_hash: str
    domain_id: str
    snapshot_paths: list[str] = Field(default_factory=list)
    created_at: str


class ReviewFlag(_Model):
    id: str
    domain_id: str
    role_id: str
    modality: str
    severity: str
    code: str
    message: str
    created_at: str
    requires_32b: bool = False


class RoleGraph(_Model):
    id: str
    domain_id: str
    role_id: str
    modality: str
    source_artifact_id: str
    source_ref: SourceRef
    summary: str
    confidence: float
    created_at: str


class PageRefOrSheetRef(_Model):
    name: str | None = None
    page_number: int | None = None


class EvidenceObject(_Model):
    object_id: str
    object_type: str
    text: str | None = None
    page_ref_or_sheet_ref: PageRefOrSheetRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceChunk(_Model):
    id: str
    domain_id: str
    role_id: str
    modality: str
    content_kind: str
    raw_text: str
    normalized_text: str
    source_ref: SourceRef
    token_estimate: int
    signal_tags: list[str] = Field(default_factory=list)
    negative_signal_tags: list[str] = Field(default_factory=list)
    parser_refs: list[str] = Field(default_factory=list)
    confidence: float
    created_at: str
    bounding_box: BoundingBox | None = None


class FieldClaim(_Model):
    id: str
    domain_id: str
    role_id: str
    modality: str
    target_layer: str
    field_name: str
    field_path: str
    candidate_value: Any
    normalized_value: Any | None = None
    schema_ref: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float
    claim_status: str
    created_at: str


class ProfessionalServicesPreDraft(_Model):
    project_summary: str | None = None


class PlannerInput(_Model):
    domain_id: str
    config_snapshot_ref: ConfigSnapshotRef
    role_graphs: list[RoleGraph] = Field(default_factory=list)
    field_claims: list[FieldClaim] = Field(default_factory=list)
    authority_weights: list[Any] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    contradiction_flags: list[Any] = Field(default_factory=list)
    planner_notes: list[str] = Field(default_factory=list)


class PlannerOutput(_Model):
    domain_id: str
    config_snapshot_ref: ConfigSnapshotRef
    canonical_pre_draft: ProfessionalServicesPreDraft
    contradiction_flags: list[Any] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    planner_summary: str
    confidence: float


__all__ = [
    "BoundingBox",
    "ConfigSnapshotRef",
    "EvidenceChunk",
    "EvidenceObject",
    "FieldClaim",
    "PageRefOrSheetRef",
    "PlannerInput",
    "PlannerOutput",
    "ProfessionalServicesPreDraft",
    "ReviewFlag",
    "RoleGraph",
    "SourceRef",
]
