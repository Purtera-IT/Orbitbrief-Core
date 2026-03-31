from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from .config import allowed_business_fields, executable_pre_schema_ref, implemented_roles, post_schema_ref, role_config, supported_modalities_for_role


class SpineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SourceRef(SpineModel):
    artifact_id: str
    artifact_name: str
    artifact_path: str
    artifact_hash: str
    workbook: str | None = None
    workbook_sheet: str | None = None
    workbook_cell: str | None = None
    schema_ref: str | None = None


class PageOrSheetRef(SpineModel):
    index: int | None = None
    name: str | None = None
    kind: Literal["page", "sheet", "container", "artifact"] = "artifact"


class BoundingBox(SpineModel):
    x0: float
    y0: float
    x1: float
    y1: float


class EvidenceChunk(SpineModel):
    id: str
    object_type: Literal["EvidenceChunk"] = "EvidenceChunk"
    domain_id: str
    role_id: str
    modality: str
    content_kind: str
    raw_text: str
    normalized_text: str
    source_ref: SourceRef
    page_ref_or_sheet_ref: PageOrSheetRef | None = None
    bbox: BoundingBox | None = None
    token_estimate: int | None = None
    signal_tags: list[str] = Field(default_factory=list)
    negative_signal_tags: list[str] = Field(default_factory=list)
    parser_refs: list[str] = Field(default_factory=list)
    confidence: float
    created_at: datetime


class TableObject(SpineModel):
    id: str
    object_type: Literal["TableObject"] = "TableObject"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    page_ref_or_sheet_ref: PageOrSheetRef
    headers_raw: list[str]
    headers_normalized: list[str]
    column_count: int
    row_refs: list[str] = Field(default_factory=list)
    parser_refs: list[str] = Field(default_factory=list)
    confidence: float
    created_at: datetime


class RowObject(SpineModel):
    id: str
    object_type: Literal["RowObject"] = "RowObject"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    parent_table_id: str
    row_index: int
    raw_cells: dict[str, Any]
    normalized_cells: dict[str, Any]
    row_type: str
    entity_keys: list[str] = Field(default_factory=list)
    confidence: float
    created_at: datetime


class SheetObject(SpineModel):
    id: str
    object_type: Literal["SheetObject"] = "SheetObject"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    page_or_sheet_index: int
    page_or_sheet_name: str
    sheet_kind: str
    title_block: dict[str, Any] | None = None
    revision_block: dict[str, Any] | None = None
    extracted_text_ref_ids: list[str] = Field(default_factory=list)
    confidence: float
    created_at: datetime


class ImageCrop(SpineModel):
    id: str
    object_type: Literal["ImageCrop"] = "ImageCrop"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    parent_sheet_id: str
    crop_kind: str
    bbox: BoundingBox
    derived_text: str | None = None
    confidence: float
    created_at: datetime


class DiagramNode(SpineModel):
    id: str
    object_type: Literal["DiagramNode"] = "DiagramNode"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    parent_sheet_id: str
    node_type: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    bbox: BoundingBox | None = None
    confidence: float
    created_at: datetime


class DiagramEdge(SpineModel):
    id: str
    object_type: Literal["DiagramEdge"] = "DiagramEdge"
    domain_id: str
    role_id: str
    modality: str
    source_ref: SourceRef
    parent_sheet_id: str
    src_node_id: str
    dst_node_id: str
    relation_type: str
    label: str | None = None
    confidence: float
    created_at: datetime


class AuthorityWeight(SpineModel):
    id: str
    object_type: Literal["AuthorityWeight"] = "AuthorityWeight"
    domain_id: str
    role_id: str
    modality: str
    field_name: str
    weight: float
    basis: str
    notes: str | None = None
    created_at: datetime


class FieldClaim(SpineModel):
    id: str
    object_type: Literal["FieldClaim"] = "FieldClaim"
    domain_id: str
    role_id: str
    modality: str
    target_layer: Literal["pre_field", "post_hint"]
    field_name: str
    field_path: str
    candidate_value: Any
    normalized_value: Any
    schema_ref: str
    evidence_refs: list[str] = Field(default_factory=list)
    authority_weight_ref: str | None = None
    confidence: float
    claim_status: Literal["asserted", "inferred", "conflicting", "rejected", "deferred"]
    notes: str | None = None
    created_at: datetime


class ReviewFlag(SpineModel):
    id: str
    object_type: Literal["ReviewFlag"] = "ReviewFlag"
    domain_id: str
    role_id: str
    modality: str
    severity: Literal["low", "medium", "high"]
    code: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    component_id: str | None = None
    requires_32b: bool = False
    requires_human: bool = False
    created_at: datetime


class ContradictionFlag(SpineModel):
    id: str
    object_type: Literal["ContradictionFlag"] = "ContradictionFlag"
    domain_id: str
    field_name: str
    conflicting_claim_refs: list[str]
    severity: Literal["low", "medium", "high"]
    resolution_status: Literal["open", "resolved", "deferred"]
    notes: str | None = None
    created_at: datetime


class RoleGraph(SpineModel):
    id: str
    object_type: Literal["RoleGraph"] = "RoleGraph"
    domain_id: str
    role_id: str
    modality: str
    source_artifact_id: str
    source_ref: SourceRef
    node_refs: list[str] = Field(default_factory=list)
    edge_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    field_claim_refs: list[str] = Field(default_factory=list)
    review_flag_refs: list[str] = Field(default_factory=list)
    summary: str
    confidence: float
    created_at: datetime


class ConfigSnapshotRef(SpineModel):
    id: str
    object_type: Literal["ConfigSnapshotRef"] = "ConfigSnapshotRef"
    snapshot_id: str
    snapshot_hash: str
    domain_id: str
    snapshot_paths: list[str]
    created_at: datetime


class ProvenanceRecord(SpineModel):
    id: str
    object_type: Literal["ProvenanceRecord"] = "ProvenanceRecord"
    pipeline_run_id: str
    pipeline_step: str
    domain_id: str
    role_id: str | None = None
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    config_snapshot_ref: ConfigSnapshotRef
    status: Literal["started", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    notes: str | None = None


class PipelineStepEvent(SpineModel):
    id: str
    pipeline_run_id: str
    step_name: str
    domain_id: str
    role_id: str | None = None
    event_type: str
    message: str
    related_object_refs: list[str] = Field(default_factory=list)
    timestamp: datetime


def build_professional_services_pre_draft_model() -> type[BaseModel]:
    fields: dict[str, tuple[Any, None]] = {}
    seen: set[str] = set()
    for role_id in implemented_roles():
        for modality in supported_modalities_for_role(role_id):
            pre_ref = executable_pre_schema_ref(role_id, modality)
            for field_name in allowed_business_fields(pre_ref):
                if field_name in seen:
                    continue
                seen.add(field_name)
                fields[field_name] = (Any | None, None)
    model = create_model(  # type: ignore[call-overload]
        "ProfessionalServicesPreDraft",
        __base__=SpineModel,
        __config__=ConfigDict(
            title="professional_services_pre_draft",
            json_schema_extra={
                "runtime_draft": True,
                "not_final_canonical_contract": True,
                "domain_id": "professional_services",
            },
        ),
        **fields,
    )
    return model


ProfessionalServicesPreDraft = build_professional_services_pre_draft_model()


class PlannerInput(SpineModel):
    domain_id: str
    config_snapshot_ref: ConfigSnapshotRef
    role_graphs: list[RoleGraph]
    field_claims: list[FieldClaim]
    authority_weights: list[AuthorityWeight]
    review_flags: list[ReviewFlag]
    contradiction_flags: list[ContradictionFlag]
    planner_notes: list[str] = Field(default_factory=list)


class PlannerOutput(SpineModel):
    domain_id: str
    config_snapshot_ref: ConfigSnapshotRef
    canonical_pre_draft: ProfessionalServicesPreDraft
    contradiction_flags: list[ContradictionFlag] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    planner_summary: str
    confidence: float


def contract_model_registry() -> dict[str, type[BaseModel]]:
    return {
        "evidence_chunk": EvidenceChunk,
        "table_object": TableObject,
        "row_object": RowObject,
        "sheet_object": SheetObject,
        "image_crop": ImageCrop,
        "diagram_node": DiagramNode,
        "diagram_edge": DiagramEdge,
        "role_graph": RoleGraph,
        "field_claim": FieldClaim,
        "authority_weight": AuthorityWeight,
        "review_flag": ReviewFlag,
        "contradiction_flag": ContradictionFlag,
        "provenance_record": ProvenanceRecord,
        "pipeline_step_event": PipelineStepEvent,
        "config_snapshot_ref": ConfigSnapshotRef,
        "planner_input": PlannerInput,
        "planner_output": PlannerOutput,
        "professional_services_pre_draft": ProfessionalServicesPreDraft,
    }
