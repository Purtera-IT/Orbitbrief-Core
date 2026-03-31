import json
from pathlib import Path

from orbitbrief_core.runtime_spine.contracts import (
    BoundingBox,
    ConfigSnapshotRef,
    EvidenceChunk,
    FieldClaim,
    PlannerInput,
    PlannerOutput,
    ProfessionalServicesPreDraft,
    ReviewFlag,
    RoleGraph,
    SourceRef,
)
from orbitbrief_core.runtime_spine.validators import validate_against_schema


def test_evidence_chunk_validates_against_json_schema():
    chunk = EvidenceChunk(
        id="chunk_1",
        domain_id="professional_services",
        role_id="transcript_or_notes",
        modality="txt",
        content_kind="paragraph",
        raw_text="hello",
        normalized_text="hello",
        source_ref=SourceRef(artifact_id="a1", artifact_name="a.txt", artifact_path="/tmp/a.txt", artifact_hash="hash"),
        token_estimate=1,
        signal_tags=[],
        negative_signal_tags=[],
        parser_refs=["parser"],
        confidence=0.9,
        created_at="2026-03-30T00:00:00Z",
    )
    validate_against_schema("evidence_chunk", chunk.model_dump(mode="json", exclude_none=True))


def test_planner_contracts_validate_against_json_schema():
    cfg = ConfigSnapshotRef(
        id="cfg_1",
        snapshot_id="snap",
        snapshot_hash="hash",
        domain_id="professional_services",
        snapshot_paths=["config/domains/professional_services/domain.yaml"],
        created_at="2026-03-30T00:00:00Z",
    )
    graph = RoleGraph(
        id="graph_1",
        domain_id="professional_services",
        role_id="transcript_or_notes",
        modality="txt",
        source_artifact_id="artifact_1",
        source_ref=SourceRef(artifact_id="a1", artifact_name="a.txt", artifact_path="/tmp/a.txt", artifact_hash="hash"),
        summary="summary",
        confidence=0.8,
        created_at="2026-03-30T00:00:00Z",
    )
    flag = ReviewFlag(
        id="flag_1",
        domain_id="professional_services",
        role_id="transcript_or_notes",
        modality="txt",
        severity="low",
        code="demo",
        message="demo",
        created_at="2026-03-30T00:00:00Z",
    )
    claim = FieldClaim(
        id="claim_1",
        domain_id="professional_services",
        role_id="transcript_or_notes",
        modality="txt",
        target_layer="pre_field",
        field_name="project_summary",
        field_path="project_summary",
        candidate_value="summary",
        normalized_value="summary",
        schema_ref="transcript_or_notes.txt.pre",
        evidence_refs=[],
        confidence=0.7,
        claim_status="asserted",
        created_at="2026-03-30T00:00:00Z",
    )
    planner_input = PlannerInput(
        domain_id="professional_services",
        config_snapshot_ref=cfg,
        role_graphs=[graph],
        field_claims=[claim],
        authority_weights=[],
        review_flags=[flag],
        contradiction_flags=[],
        planner_notes=[],
    )
    draft = ProfessionalServicesPreDraft(project_summary="summary")
    planner_output = PlannerOutput(
        domain_id="professional_services",
        config_snapshot_ref=cfg,
        canonical_pre_draft=draft,
        contradiction_flags=[],
        review_flags=[flag],
        planner_summary="ok",
        confidence=0.8,
    )
    validate_against_schema("planner_input", planner_input.model_dump(mode="json", exclude_none=True))
    validate_against_schema("planner_output", planner_output.model_dump(mode="json", exclude_none=True))
