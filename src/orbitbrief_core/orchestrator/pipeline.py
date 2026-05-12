"""End-to-end pipeline: ``envelope.json`` → reviewable brief.

Stage map (matches the artifact-directory prefixes):

* **00 ingest** — load and re-emit the canonical envelope.
* **01 evidence_runtime** — ingest into DuckDB-backed runtime.
* **10 pack_prior** — Phase-3 keyword scorer.
* **11 site_reality** — Phase-3 graph clusterer.
* **20 retrieval_bundles** — one bundle per active pack.
* **30 planner** — Phase-4 BriefState (LLM, optional escalation).
* **31 refiner** — Phase-4 graph-consistency cleanup.
* **40 brains** — one brain per active pack (Phase 5).
* **50 validator** — per brain output (Phase 6).
* **60 calibrator** — per brain output (Phase 6).
* **70 review_queue** — needs_review + reject items enqueued.
* **71 training_log** — handed to the orchestrator caller; the
  pipeline does NOT auto-create reviewer decisions.

Every stage logs a :class:`StageRecord`. Final ``pipeline_log.json``
captures the whole audit trail, including timings, fallback usage,
and per-pack outputs.

Without a chat client (no ``--ollama`` / no client passed at
construction) the planner + brain stages SKIP rather than blow up.
That's the path the smoke tests exercise: the pipeline still runs
to completion and writes the substrate artifacts; later runs can
re-attach a real client and resume.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.calibrator import Calibrator, CalibratorReport
from orbitbrief_core.calibrator.verdict import Verdict
from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime
from orbitbrief_core.inference.client import ChatClient
from orbitbrief_core.orchestrator.artifacts import (
    BriefArtifacts,
    StageRecord,
    StageStatus,
)
from orbitbrief_core.orchestrator.brain_registry import (
    BrainRegistry,
    default_brain_registry,
)
from orbitbrief_core.orchestrator.bundle_assembler import BundleAssembler
from orbitbrief_core.review_runtime import (
    InMemoryTrainingLog,
    JsonlReviewQueue,
    JsonlTrainingLog,
)
from orbitbrief_core.validator import (
    BrainOutputValidator,
    RuntimeEvidenceLookup,
    ValidationReport,
)
from orbitbrief_core.world_model.pack_prior import PackPrior, PackPriorState
from orbitbrief_core.world_model.planner import (
    BriefState,
    Planner,
    PlannerResult,
)
from orbitbrief_core.world_model.refiner import refine_brief
from orbitbrief_core.world_model.site_reality import (
    SiteRealityEngine,
    SiteRealityState,
)


@dataclass
class PipelineConfig:
    """Knobs the orchestrator caller can tweak per run."""

    # Pack-confidence floor for "active enough to ground a brain".
    active_pack_floor: float = 0.05
    # If True, persist the review queue + training log to JSONL on disk.
    persist_review_queue: bool = True
    # If True, enqueue NEEDS_REVIEW + REJECT items into the review queue.
    enqueue_review_items: bool = True


@dataclass
class PipelineResult:
    """Orchestrator return: per-stage outputs + the artifacts handle."""

    artifacts: BriefArtifacts
    pack_prior: PackPriorState | None = None
    site_reality: SiteRealityState | None = None
    bundles: dict[str, RetrievalBundle] = field(default_factory=dict)
    planner_result: PlannerResult | None = None
    refined_brief: BriefState | None = None
    brain_states: dict[str, Any] = field(default_factory=dict)
    validations: dict[str, ValidationReport] = field(default_factory=dict)
    calibrations: dict[str, CalibratorReport] = field(default_factory=dict)
    queued_count: int = 0
    stage_records: list[StageRecord] = field(default_factory=list)
    skipped_brains_no_chat: bool = False


@dataclass
class BriefPipeline:
    """Runs Phases 0–6 against one envelope, writing artifacts as it goes."""

    chat_client: ChatClient | None = None
    brain_registry: BrainRegistry = field(default_factory=default_brain_registry)
    planner_default_model: str = "qwen3:14b"
    planner_escalated_model: str = "qwen3:32b"
    pack_prior_chat_model: str = "qwen3:14b"
    site_reality_chat_model: str = "qwen3:14b"
    config: PipelineConfig = field(default_factory=PipelineConfig)

    def compile(
        self, envelope_path: Path | str, *, out_dir: Path | str
    ) -> PipelineResult:
        """End-to-end: ``envelope.json`` → ``out_dir/`` of artifacts."""
        envelope_path = Path(envelope_path)
        artifacts = BriefArtifacts(Path(out_dir))
        records: list[StageRecord] = []

        # 00 + 01: load envelope, build evidence runtime.
        runtime, env_record = self._stage_load_runtime(envelope_path, artifacts)
        records.append(env_record)

        try:
            return self._compile_with_runtime(runtime, artifacts, records, envelope_path)
        finally:
            runtime.close()

    def _compile_with_runtime(
        self,
        runtime: EvidenceRuntime,
        artifacts: BriefArtifacts,
        records: list[StageRecord],
        envelope_path: Path,
    ) -> PipelineResult:
        result = PipelineResult(artifacts=artifacts)

        # 10 pack_prior.
        pp_state, rec = self._run_stage(
            "10_pack_prior",
            lambda: PackPrior.with_default_registry(
                chat_client=self.chat_client,
                chat_model_id=self.pack_prior_chat_model,
            ).compute(runtime),
            artifact=artifacts.pack_prior_path,
        )
        result.pack_prior = pp_state
        records.append(rec)

        # 11 site_reality.
        sr_state, rec = self._run_stage(
            "11_site_reality",
            lambda: SiteRealityEngine(
                chat_client=self.chat_client,
                chat_model_id=self.site_reality_chat_model,
            ).compute(runtime),
            artifact=artifacts.site_reality_path,
        )
        result.site_reality = sr_state
        records.append(rec)

        # 20 retrieval bundles per active pack.
        active_packs = self._pick_active_packs(pp_state)
        bundles: dict[str, RetrievalBundle] = {}
        assembler = BundleAssembler(runtime=runtime)
        for pack_id in active_packs:
            bundle, rec = self._run_stage(
                f"20_retrieval_bundles::{pack_id}",
                lambda pid=pack_id: assembler.assemble(pack_id=pid),
                artifact=artifacts.retrieval_bundle_path(pack_id),
            )
            bundles[pack_id] = bundle
            records.append(rec)
        result.bundles = bundles

        # 30 planner + 31 refiner — only with a chat client.
        if self.chat_client is None:
            result.skipped_brains_no_chat = True
            records.append(
                _skipped_record(
                    "30_planner",
                    detail={"reason": "no chat_client; planner requires LLM"},
                )
            )
            records.append(_skipped_record("31_refiner"))
            for pack_id in active_packs:
                records.append(
                    _skipped_record(
                        f"40_brain::{pack_id}",
                        detail={"reason": "no chat_client"},
                    )
                )
                records.append(_skipped_record(f"50_validator::{pack_id}"))
                records.append(_skipped_record(f"60_calibrator::{pack_id}"))
            records.append(_skipped_record("70_review_queue"))
            artifacts.write_pipeline_log(records)
            artifacts.write_manifest(self._manifest(envelope_path, result, records))
            result.stage_records = records
            return result

        planner = Planner(
            chat_client=self.chat_client,
            default_model=self.planner_default_model,
            escalated_model=self.planner_escalated_model,
        )
        planner_result, rec = self._run_stage(
            "30_planner",
            lambda: planner.compose(
                runtime, pack_prior=pp_state, site_reality=sr_state
            ),
            artifact=artifacts.brief_state_raw_path,
            payload_extractor=lambda r: r.state,
            extra_detail=lambda r: {
                "tier": r.escalation.tier.value,
                "fallback_used": r.fallback_used,
                "validation_errors": list(r.validation_errors),
                "token_cost": r.usage.to_dict(),
            },
            fallback_status=lambda r: (
                StageStatus.FALLBACK if r.fallback_used else StageStatus.OK
            ),
        )
        result.planner_result = planner_result
        records.append(rec)

        refined, rec = self._run_stage(
            "31_refiner",
            lambda: refine_brief(
                planner_result.state,
                runtime=runtime,
                pack_prior=pp_state,
                site_reality=sr_state,
            ),
            artifact=artifacts.brief_state_refined_path,
            payload_extractor=lambda r: r.state,
            extra_detail=lambda r: r.to_dict(),
        )
        result.refined_brief = refined.state
        records.append(rec)

        # 40 brains per active pack with a registered factory.
        validator = BrainOutputValidator(
            lookup=RuntimeEvidenceLookup(runtime=runtime)
        )
        calibrator = Calibrator()
        queue = (
            JsonlReviewQueue(artifacts.review_queue_dir)
            if self.config.persist_review_queue
            else None
        )
        training_log = (
            JsonlTrainingLog(artifacts.review_queue_dir)
            if self.config.persist_review_queue
            else InMemoryTrainingLog()
        )
        # The training log isn't populated here (no decisions yet);
        # it's wired so subsequent reviewer decisions land in the
        # right file. Touch it so the file exists.
        _ = training_log

        for pack_id in active_packs:
            factory = self.brain_registry.get(pack_id)
            if factory is None:
                records.append(
                    _skipped_record(
                        f"40_brain::{pack_id}",
                        detail={"reason": "no registered brain for pack_id"},
                    )
                )
                records.append(_skipped_record(f"50_validator::{pack_id}"))
                records.append(_skipped_record(f"60_calibrator::{pack_id}"))
                continue

            brain = factory(self.chat_client)  # type: ignore[arg-type]
            brain_result, rec = self._run_stage(
                f"40_brain::{pack_id}",
                lambda b=brain, br=refined.state, bd=bundles[pack_id]: b.compose(br, bd),
                artifact=artifacts.brain_output_path(pack_id),
                payload_extractor=lambda r: r.state,
                extra_detail=lambda r: {
                    "fallback_used": r.fallback_used,
                    "unresolved_packet_ids": list(r.unresolved_packet_ids),
                    "unresolved_atom_ids": list(r.unresolved_atom_ids),
                    "token_cost": r.usage.to_dict(),
                },
                fallback_status=lambda r: (
                    StageStatus.FALLBACK if r.fallback_used else StageStatus.OK
                ),
            )
            result.brain_states[pack_id] = brain_result.state
            records.append(rec)

            validation_report, rec = self._run_stage(
                f"50_validator::{pack_id}",
                lambda s=brain_result.state, br=refined.state, bd=bundles[pack_id]: (
                    validator.validate_managed_services(s, brief=br, bundle=bd)
                ),
                artifact=artifacts.validation_path(pack_id),
                extra_detail=lambda r: {
                    "rule_counts": r.rule_counts(),
                    "n_passed": len(r.passed_items),
                    "n_failed": len(r.failed_items),
                    "n_blocker": len(r.blocker_items),
                },
            )
            result.validations[pack_id] = validation_report
            records.append(rec)

            calibration_report, rec = self._run_stage(
                f"60_calibrator::{pack_id}",
                lambda s=brain_result.state, v=validation_report, br=refined.state, bd=bundles[pack_id]: (
                    calibrator.calibrate_managed_services(
                        s, validation=v, brief=br, bundle=bd
                    )
                ),
                artifact=artifacts.calibration_path(pack_id),
                extra_detail=lambda r: {
                    "by_verdict_counts": {
                        k: len(v) for k, v in r.by_verdict().items()
                    },
                },
            )
            result.calibrations[pack_id] = calibration_report
            records.append(rec)

            if queue is not None and self.config.enqueue_review_items:
                queued = 0
                for item in calibration_report.items:
                    if item.verdict is Verdict.AUTO_ACCEPT:
                        continue
                    queue.enqueue(item)
                    queued += 1
                result.queued_count += queued
                records.append(
                    StageRecord(
                        stage=f"70_review_queue::{pack_id}",
                        status=StageStatus.OK,
                        started_at=_iso_now(),
                        finished_at=_iso_now(),
                        duration_ms=0,
                        artifact_path=str(artifacts.review_queue_dir),
                        detail={"queued": queued},
                    )
                )

        artifacts.write_pipeline_log(records)
        artifacts.write_manifest(self._manifest(envelope_path, result, records))
        result.stage_records = records
        return result

    # ───── stage helpers ─────

    def _stage_load_runtime(
        self, envelope_path: Path, artifacts: BriefArtifacts
    ) -> tuple[EvidenceRuntime, StageRecord]:
        start = perf_counter()
        started = _iso_now()
        # Load the envelope dict and write the canonical copy.
        text = envelope_path.read_text(encoding="utf-8")
        envelope_dict = json.loads(text)
        artifacts.write_json(artifacts.envelope_path, envelope_dict)
        runtime = EvidenceRuntime.from_envelope(envelope_dict)
        finished = _iso_now()
        rec = StageRecord(
            stage="00_ingest_envelope",
            status=StageStatus.OK,
            started_at=started,
            finished_at=finished,
            duration_ms=int((perf_counter() - start) * 1000),
            artifact_path=str(artifacts.envelope_path),
            detail={
                "envelope_path": str(envelope_path),
                "atom_count": len(envelope_dict.get("atoms") or []),
                "packet_count": len(envelope_dict.get("packets") or []),
                "entity_count": len(envelope_dict.get("entities") or []),
            },
        )
        return runtime, rec

    def _run_stage(
        self,
        stage: str,
        thunk,
        *,
        artifact: Path,
        payload_extractor=None,
        extra_detail=None,
        fallback_status=None,
    ) -> tuple[Any, StageRecord]:
        """Run ``thunk()``, write its artifact, and return (result, record)."""
        start = perf_counter()
        started = _iso_now()
        try:
            value = thunk()
        except Exception as exc:
            duration = int((perf_counter() - start) * 1000)
            record = StageRecord(
                stage=stage,
                status=StageStatus.FAILED,
                started_at=started,
                finished_at=_iso_now(),
                duration_ms=duration,
                artifact_path=None,
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None, record

        payload = payload_extractor(value) if payload_extractor is not None else value
        self._write(artifact, payload)

        status = StageStatus.OK
        if fallback_status is not None:
            try:
                status = fallback_status(value) or StageStatus.OK
            except Exception:
                status = StageStatus.OK
        detail = extra_detail(value) if extra_detail is not None else {}
        record = StageRecord(
            stage=stage,
            status=status,
            started_at=started,
            finished_at=_iso_now(),
            duration_ms=int((perf_counter() - start) * 1000),
            artifact_path=str(artifact),
            detail=detail or {},
        )
        return value, record

    def _write(self, artifact: Path, payload: Any) -> None:
        """Write ``payload`` to ``artifact`` as JSON (uses BriefArtifacts.write_json)."""
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        artifact.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _pick_active_packs(self, pack_prior: PackPriorState) -> list[str]:
        active: list[str] = []
        floor = self.config.active_pack_floor
        # Top pack always gets a brain run (subject to factory existing).
        for s in pack_prior.scores:
            if s.confidence >= floor or s.pack_id == pack_prior.top_pack_id:
                active.append(s.pack_id)
            if len(active) >= 4:  # cap fan-out to 4 brains per engagement
                break
        # Always include the top pack even if it slipped past the floor.
        if pack_prior.top_pack_id not in active:
            active.insert(0, pack_prior.top_pack_id)
        # Filter to packs the registry can actually serve.
        seen = set()
        ordered = []
        for p in active:
            if p in seen:
                continue
            seen.add(p)
            ordered.append(p)
        return ordered

    def _manifest(
        self,
        envelope_path: Path,
        result: PipelineResult,
        records: list[StageRecord],
    ) -> dict[str, Any]:
        return {
            "envelope_path": str(envelope_path),
            "generated_at": _iso_now(),
            "active_packs": list(result.bundles.keys()),
            "brains_run": list(result.brain_states.keys()),
            "queued_for_review": result.queued_count,
            "skipped_brains_no_chat": result.skipped_brains_no_chat,
            "stage_count": len(records),
            "stage_status_counts": _count_statuses(records),
        }


# ────────────────────────────── helpers ────────────────────────────────


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _skipped_record(stage: str, *, detail: dict[str, Any] | None = None) -> StageRecord:
    return StageRecord(
        stage=stage,
        status=StageStatus.SKIPPED,
        started_at=_iso_now(),
        finished_at=_iso_now(),
        duration_ms=0,
        artifact_path=None,
        detail=detail or {},
    )


def _count_statuses(records: list[StageRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r.status.value] = out.get(r.status.value, 0) + 1
    return out
