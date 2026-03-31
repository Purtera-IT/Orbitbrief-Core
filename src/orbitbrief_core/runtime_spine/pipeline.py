from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import config_snapshot_ref
from .contracts import ConfigSnapshotRef
from .heads import authority_head, complexity_head, integrity_head, modality_head, review_calibrator, role_head, site_head
from .ingestors import ingest
from .planner import build_planner_input, build_planner_output
from .provenance import ProvenanceRecorder
from .shared import make_id, utc_now
from .validators import planner_output_validator, pre_validator, runtime_output_validator


def build_config_snapshot_model() -> ConfigSnapshotRef:
    snap = config_snapshot_ref()
    return ConfigSnapshotRef(
        id=make_id("config"),
        snapshot_id=snap["snapshot_id"],
        snapshot_hash=snap["snapshot_hash"],
        domain_id=snap["domain_id"],
        snapshot_paths=snap["snapshot_paths"],
        created_at=utc_now(),
    )


def run_pipeline(path: str | Path, domain_id: str = "professional_services") -> dict[str, Any]:
    source_path = Path(path)
    pipeline_run_id = make_id("run")
    snapshot = build_config_snapshot_model()
    recorder = ProvenanceRecorder(snapshot)

    integrity = integrity_head(source_path)
    recorder.record_completed(pipeline_run_id, "integrity_head", domain_id, None, [str(source_path)], [flag.id for flag in integrity["review_flags"]], notes="Integrity head executed.")

    modality = modality_head(source_path)
    recorder.record_completed(pipeline_run_id, "modality_head", domain_id, None, [str(source_path)], [], notes="Modality head executed.")

    role_result = role_head(source_path, modality["modality"])
    recorder.record_completed(pipeline_run_id, "role_head", domain_id, role_result["role_id"], [str(source_path)], [], notes="Role head executed.")

    if not role_result["role_id"]:
        return {"pipeline_run_id": pipeline_run_id, "config_snapshot_ref": snapshot, "integrity": integrity, "modality": modality, "role_result": role_result, "review_decision": {"decision": "needs_human_review", "reasons": ["role_unresolved"]}, "provenance": recorder.emit_bundle()}

    if role_result["status"] == "parked":
        review_decision = {"decision": "needs_human_review", "reasons": [role_result["status"]]}
        recorder.record_completed(
            pipeline_run_id,
            "review_calibrator",
            domain_id,
            role_result["role_id"],
            [str(source_path)],
            [],
            notes="Role is not executable in Stage 2 runtime.",
        )
        return {
            "pipeline_run_id": pipeline_run_id,
            "config_snapshot_ref": snapshot,
            "integrity": integrity,
            "modality": modality,
            "role_result": role_result,
            "review_decision": review_decision,
            "provenance": recorder.emit_bundle(),
        }

    complexity = complexity_head(source_path, role_result["role_id"], modality["modality"])
    recorder.record_completed(pipeline_run_id, "complexity_head", domain_id, role_result["role_id"], [str(source_path)], [flag.id for flag in complexity["review_flags"]], notes="Complexity head executed.")

    ingested = ingest(role_result["role_id"], source_path, modality["modality"])
    recorder.record_completed(
        pipeline_run_id,
        "ingestor",
        domain_id,
        role_result["role_id"],
        [str(source_path)],
        [obj.id for obj in ingested["evidence_objects"]] + [claim.id for claim in ingested["field_claims"]],
        notes="Role ingestor executed.",
    )

    authority_weights = authority_head(role_result["role_id"], modality["modality"])
    recorder.record_completed(pipeline_run_id, "authority_head", domain_id, role_result["role_id"], [claim.id for claim in ingested["field_claims"]], [w.id for w in authority_weights], notes="Authority head executed.")

    site_prior = site_head(ingested["field_claims"])
    recorder.record_completed(pipeline_run_id, "site_head", domain_id, role_result["role_id"], [claim.id for claim in ingested["field_claims"]], [], notes="Site head executed.")

    planner_input = build_planner_input(
        domain_id=domain_id,
        config_snapshot_ref=snapshot,
        role_graphs=[ingested["role_graph"]],
        field_claims=ingested["field_claims"],
        authority_weights=authority_weights,
        review_flags=integrity["review_flags"] + complexity["review_flags"] + ingested["review_flags"],
        planner_notes=[f"site_prior={site_prior}"],
    )
    planner_output = build_planner_output(planner_input)
    recorder.record_completed(
        pipeline_run_id,
        "planner_shell",
        domain_id,
        role_result["role_id"],
        [claim.id for claim in ingested["field_claims"]],
        [flag.id for flag in planner_output.review_flags] + [flag.id for flag in planner_output.contradiction_flags],
        notes="Planner shell executed.",
    )

    pre_validator(planner_output.canonical_pre_draft)
    runtime_output_validator(ingested["evidence_objects"] + ingested["field_claims"] + authority_weights + planner_output.review_flags + planner_output.contradiction_flags + [ingested["role_graph"], snapshot])
    planner_output_validator(planner_output)
    recorder.record_completed(pipeline_run_id, "validation", domain_id, role_result["role_id"], [planner_output.canonical_pre_draft.__class__.__name__], [], notes="Validators executed.")

    review_decision = review_calibrator(
        integrity=integrity,
        role_result=role_result,
        complexity=complexity,
        review_flags=planner_output.review_flags,
    )
    recorder.record_completed(pipeline_run_id, "review_calibrator", domain_id, role_result["role_id"], [flag.id for flag in planner_output.review_flags], [], notes="Review calibrator executed.")

    return {
        "pipeline_run_id": pipeline_run_id,
        "config_snapshot_ref": snapshot,
        "integrity": integrity,
        "modality": modality,
        "role_result": role_result,
        "complexity": complexity,
        "site_prior": site_prior,
        "ingested": ingested,
        "authority_weights": authority_weights,
        "planner_input": planner_input,
        "planner_output": planner_output,
        "review_decision": review_decision,
        "provenance": recorder.emit_bundle(),
    }
