from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


TEXT_NARRATIVE_PARSER_IO_VERSION = "1.0.0"


class NarrativeSegmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    block_type: str
    text: str
    normalized_text: str
    section_label: str | None = None
    sender_label: str | None = None
    message_index: int | None = None
    source_offsets: dict[str, int] = Field(default_factory=dict)
    modality: str
    tags: list[str] = Field(default_factory=list)


class TextNarrativeParserInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    io_version: str = TEXT_NARRATIVE_PARSER_IO_VERSION
    domain_id: str
    role_id: str
    modality: str
    source_schema_ref: str
    allowed_fields: list[str]
    allowed_field_paths: list[str] = Field(default_factory=list)
    normalized_artifact_text: str
    modality_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_bundle: list[dict[str, Any]] = Field(default_factory=list)


class TextNarrativeParserOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    io_version: str = TEXT_NARRATIVE_PARSER_IO_VERSION
    parser_id: str
    parser_version: str
    modality: str
    source_path: str
    source_hash: str
    segments: list[NarrativeSegmentV1]
