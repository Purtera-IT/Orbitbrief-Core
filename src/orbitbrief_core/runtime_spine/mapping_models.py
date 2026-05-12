from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class HeaderPosition(_Model):
    sheet_index: int
    column_index: int


class ValueProfile(_Model):
    dominant_type: str
    distinct_ratio: float
    null_ratio: float
    looks_like_date: bool = False
    looks_like_count: bool = False


class HeaderBundle(_Model):
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


class MappingDecision(_Model):
    decision_type: str
    target_path: str | None = None
    confidence: float = 0.0


class ApprovedAlias(_Model):
    header_alias: str
    target_path: str
    mapping_kind: str = "exact"


class CandidateObservation(_Model):
    header_raw: str
    header_normalized: str
    pipeline_run_id: str
    file_fingerprint: str


class MappingResolution(_Model):
    decision: MappingDecision
    approved_alias: ApprovedAlias | None = None
    candidate_observation: CandidateObservation | None = None


__all__ = [
    "ApprovedAlias",
    "CandidateObservation",
    "HeaderBundle",
    "HeaderPosition",
    "MappingDecision",
    "MappingResolution",
    "ValueProfile",
]
