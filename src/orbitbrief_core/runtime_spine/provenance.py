from __future__ import annotations

from typing import Any

from .contracts import ConfigSnapshotRef, PipelineStepEvent, ProvenanceRecord
from .shared import make_id, utc_now


class ProvenanceRecorder:
    def __init__(self, config_snapshot_ref: ConfigSnapshotRef) -> None:
        self.config_snapshot_ref = config_snapshot_ref
        self.records: list[ProvenanceRecord] = []
        self.events: list[PipelineStepEvent] = []

    def record_started(self, pipeline_run_id: str, step_name: str, domain_id: str, role_id: str | None, input_refs: list[str], notes: str | None = None) -> ProvenanceRecord:
        now = utc_now()
        record = ProvenanceRecord(
            id=make_id("prov"),
            pipeline_run_id=pipeline_run_id,
            pipeline_step=step_name,
            domain_id=domain_id,
            role_id=role_id,
            input_refs=input_refs,
            output_refs=[],
            config_snapshot_ref=self.config_snapshot_ref,
            status="started",
            started_at=now,
            notes=notes,
        )
        self.records.append(record)
        self.events.append(
            PipelineStepEvent(
                id=make_id("event"),
                pipeline_run_id=pipeline_run_id,
                step_name=step_name,
                domain_id=domain_id,
                role_id=role_id,
                event_type="started",
                message=f"{step_name} started",
                related_object_refs=input_refs,
                timestamp=now,
            )
        )
        return record

    def record_completed(self, pipeline_run_id: str, step_name: str, domain_id: str, role_id: str | None, input_refs: list[str], output_refs: list[str], notes: str | None = None) -> ProvenanceRecord:
        started = self.record_started(pipeline_run_id, step_name, domain_id, role_id, input_refs, notes)
        completed = started.model_copy(update={"status": "completed", "output_refs": output_refs, "completed_at": utc_now()})
        self.records[-1] = completed
        self.events.append(
            PipelineStepEvent(
                id=make_id("event"),
                pipeline_run_id=pipeline_run_id,
                step_name=step_name,
                domain_id=domain_id,
                role_id=role_id,
                event_type="completed",
                message=f"{step_name} completed",
                related_object_refs=output_refs,
                timestamp=completed.completed_at or utc_now(),
            )
        )
        return completed

    def emit_bundle(self) -> dict[str, list[Any]]:
        return {"records": self.records, "events": self.events}
